import threading
import sys
import time
import os
import os.path
import pwd
import json
import ipaddress
from datetime import datetime

from PyQt6 import QtCore, QtGui, uic, QtWidgets
from PyQt6.QtCore import QCoreApplication as QC, QEvent

from slugify import slugify

from opensnitch.utils import Icons
from opensnitch.desktop_parser import LinuxDesktopParser
from opensnitch.config import Config
from opensnitch.version import version
from opensnitch.actions import Actions
from opensnitch.plugins import PluginBase
from opensnitch.rules import Rules, Rule
from opensnitch.nodes import Nodes

from opensnitch.dialogs.prompt import _utils, _constants, _checksums, _details
import opensnitch.proto as proto
ui_pb2, ui_pb2_grpc = proto.import_()

from opensnitch.utils.network_aliases import NetworkAliases

DIALOG_UI_PATH = "%s/../../res/prompt.ui" % os.path.dirname(sys.modules[__name__].__file__)
class PromptDialog(QtWidgets.QDialog, uic.loadUiType(DIALOG_UI_PATH)[0]):
    _prompt_trigger = QtCore.pyqtSignal()
    _tick_trigger = QtCore.pyqtSignal()
    _timeout_trigger = QtCore.pyqtSignal()

    TYPE = "popups"

    def __init__(self, parent=None, appicon=None):
        QtWidgets.QDialog.__init__(self, parent, QtCore.Qt.WindowType.WindowStaysOnTopHint)
        # Other interesting flags: QtCore.Qt.Tool | QtCore.Qt.BypassWindowManagerHint
        self._cfg = Config.get()
        self._rules = Rules.instance()
        self._nodes = Nodes.instance()

        self.setupUi(self)
        self.setWindowIcon(appicon)
        self.installEventFilter(self)

        self._width = None
        self._height = None

        dialog_geometry = self._cfg.getSettings("promptDialog/geometry")
        if dialog_geometry == QtCore.QByteArray:
            self.restoreGeometry(dialog_geometry)

        self.setWindowTitle("OpenSnitch v%s" % version)

        self._actions = Actions.instance()
        self._action_list = self._actions.getByType(PluginBase.TYPE_POPUPS)
        self._configure_plugins()

        self._lock = threading.Lock()
        self._con = None
        self._rule = None
        self._local = True
        self._peer = None
        self._prompt_trigger.connect(self.on_connection_prompt_triggered)
        self._timeout_trigger.connect(self.on_timeout_triggered)
        self._tick_trigger.connect(self.on_tick_triggered)
        self._tick = int(self._cfg.getSettings(self._cfg.DEFAULT_TIMEOUT_KEY)) if self._cfg.hasKey(self._cfg.DEFAULT_TIMEOUT_KEY) else _constants.DEFAULT_TIMEOUT
        self._tick_thread = None
        self._done = threading.Event()
        self._timeout_text = ""
        self._timeout_triggered = False

        self._apps_parser = LinuxDesktopParser()

        self.whatIPCombo.setVisible(False)
        self.checkDstIP.setVisible(False)
        self.checkDstPort.setVisible(False)
        self.checkUserID.setVisible(False)
        self.appDescriptionLabel.setVisible(False)

        self._ischeckAdvanceded = False
        self.checkAdvanced.toggled.connect(self._check_advanced_toggled)

        self.checkAdvanced.clicked.connect(self._button_clicked)
        self.durationCombo.activated.connect(self._button_clicked)
        self.whatCombo.activated.connect(self._button_clicked)
        self.whatIPCombo.activated.connect(self._button_clicked)
        self.checkDstIP.clicked.connect(self._button_clicked)
        self.checkDstPort.clicked.connect(self._button_clicked)
        self.checkUserID.clicked.connect(self._button_clicked)
        self.cmdInfo.clicked.connect(self._cb_cmdinfo_clicked)
        self.cmdBack.clicked.connect(self._cb_cmdback_clicked)

        self.cmdUpdateRule.clicked.connect(lambda: self._cb_update_rule_clicked(updateAll=False))
        self.cmdUpdateRuleAll.clicked.connect(lambda: self._cb_update_rule_clicked(updateAll=True))
        self.cmdBackChecksums.clicked.connect(self._cb_cmdback_clicked)
        self.messageLabel.linkActivated.connect(self._cb_warninglbl_clicked)

        self.allowIcon = Icons.new(self, "emblem-default")
        denyIcon = Icons.new(self, "emblem-important")
        rejectIcon = Icons.new(self, "window-close")
        backIcon = Icons.new(self, "go-previous")
        infoIcon = Icons.new(self, "dialog-information")

        self.cmdInfo.setIcon(infoIcon)
        self.cmdBack.setIcon(backIcon)
        self.cmdBackChecksums.setIcon(backIcon)

        self._default_action = self._cfg.getInt(self._cfg.DEFAULT_ACTION_KEY)

        self.allowButton.clicked.connect(lambda: self._on_action_clicked(Config.ACTION_ALLOW_IDX))
        self.allowButton.setIcon(self.allowIcon)
        self._allow_text = QC.translate("popups", "Allow")
        self._action_text = [
            QC.translate("popups", "Deny"),
            QC.translate("popups", "Allow"),
            QC.translate("popups", "Reject")
        ]
        self._action_icon = [denyIcon, self.allowIcon, rejectIcon]

        m = QtWidgets.QMenu()
        m.addAction(denyIcon, self._action_text[Config.ACTION_DENY_IDX]).triggered.connect(
            lambda: self._on_action_clicked(Config.ACTION_DENY_IDX)
        )
        m.addAction(rejectIcon, self._action_text[Config.ACTION_REJECT_IDX]).triggered.connect(
            lambda: self._on_action_clicked(Config.ACTION_REJECT_IDX)
        )
        self.actionButton.setMenu(m)
        self.actionButton.setText(self._action_text[Config.ACTION_DENY_IDX])
        self.actionButton.setIcon(self._action_icon[Config.ACTION_DENY_IDX])
        if self._default_action != Config.ACTION_ALLOW_IDX:
            self.actionButton.setText(self._action_text[self._default_action])
            self.actionButton.setIcon(self._action_icon[self._default_action])
        self.actionButton.clicked.connect(self._on_deny_btn_clicked)

    def _configure_plugins(self):
        """configure the plugins that apply to this dialog.
        When configuring the plugins on a particular view, they'll add,
        change or extend the existing functionality.
        """
        for conf in self._action_list:
            action = self._action_list[conf]
            for name in action['actions']:
                try:
                    action['actions'][name].configure(self)
                except Exception as e:
                    print("popups._configure_plugins() exception:", name, " you may want to enable this plugin -", e)

    def _pre_popup_plugins(self, con):
        pass

    def _post_popup_plugins(self, conn):
        """Actions performed on the pop-up once the connection details have
        been displayed on the screen.
        """
        if self._action_list == None:
            return

        for conf in self._action_list:
            action = self._action_list[conf]
            for name in action['actions']:
                try:
                    action['actions'][name].run(self, (conn,))
                except Exception as e:
                    print("popups._post_popup_plugins() exception:", name, "-", e)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            self._stop_countdown()
            return True
        return False

    def showEvent(self, event):
        super(PromptDialog, self).showEvent(event)
        self.activateWindow()
        self.adjust_size()
        self.move_popup()

    def adjust_size(self):
        if self._width is None or self._height is None:
            self._width = self.width()
            self._height = self.height()

        self.resize(QtCore.QSize(self._width, self._height))

    def move_popup(self):
        popup_pos = self._cfg.getInt(self._cfg.DEFAULT_POPUP_POSITION)
        point = self.screen().availableGeometry()
        point = self.screen().virtualSiblingAt(QtGui.QCursor.pos()).availableGeometry()
        if popup_pos == self._cfg.POPUP_TOP_RIGHT:
            self.move(point.topRight())
        elif popup_pos == self._cfg.POPUP_TOP_LEFT:
            self.move(point.topLeft())
        elif popup_pos == self._cfg.POPUP_BOTTOM_RIGHT:
            self.move(point.bottomRight())
        elif popup_pos == self._cfg.POPUP_BOTTOM_LEFT:
            self.move(point.bottomLeft())

    def _stop_countdown(self):
        action_idx = self._cfg.getInt(self._cfg.DEFAULT_ACTION_KEY)
        if action_idx == Config.ACTION_ALLOW_IDX:
            self.allowButton.setText(self._allow_text)
            self.allowButton.setIcon(self.allowIcon)
        else:
            self.actionButton.setText(self._action_text[action_idx])
            self.actionButton.setIcon(self._action_icon[action_idx])
        if self._tick_thread != None:
            self._tick_thread.stop = True

    def _check_advanced_toggled(self, state):
        self.checkDstIP.setVisible(state)
        self.whatIPCombo.setVisible(state)
        self.destIPLabel.setVisible(not state)
        self.checkDstPort.setVisible(state == True and (self._con != None and self._con.dst_port != 0))
        self.checkUserID.setVisible(state)
        self.checkSum.setVisible(self._con.process_checksums[Config.OPERAND_PROCESS_HASH_MD5] != "" and state)
        self.checksumLabel_2.setVisible(self._con.process_checksums[Config.OPERAND_PROCESS_HASH_MD5] != "" and state)
        self.checksumLabel.setVisible(self._con.process_checksums[Config.OPERAND_PROCESS_HASH_MD5] != "" and state)
        self.stackedWidget.setCurrentIndex(_constants.PAGE_MAIN)

        self._ischeckAdvanceded = state
        self.adjust_size()
        self.move_popup()

    def _button_clicked(self):
        self._stop_countdown()

    def _cb_warninglbl_clicked(self, link):
        self._stop_countdown()
        if link == "#warning-checksum":
            self.stackedWidget.setCurrentIndex(_constants.PAGE_CHECKSUMS)

    def _cb_cmdinfo_clicked(self):
        self.stackedWidget.setCurrentIndex(_constants.PAGE_DETAILS)
        self._stop_countdown()

    def _cb_update_rule_clicked(self, updateAll=False):
        self.labelChecksumStatus.setStyleSheet('')
        curRule = self.comboChecksumRule.currentText()
        if curRule == "":
            return

        for idx in range(0, self.comboChecksumRule.count()):
            curRule = self.comboChecksumRule.itemText(idx)

            rule, error = _checksums.update_rule(self._peer, self._rules, curRule, self._con)
            if rule == None:
                self.labelChecksumStatus.setStyleSheet('color: red')
                self.labelChecksumStatus.setText("✘ " + error)
                return

            self._nodes.send_notification(
                self._peer,
                ui_pb2.Notification(
                    id=int(str(time.time()).replace(".", "")),
                    type=ui_pb2.CHANGE_RULE,
                    data="",
                    rules=[rule]
                )
            )
            self.labelChecksumStatus.setStyleSheet('color: green')
            self.labelChecksumStatus.setText("✔" + QC.translate("popups", "Rule updated."))

            if not updateAll:
                break

    def _cb_cmdback_clicked(self):
        self.stackedWidget.setCurrentIndex(_constants.PAGE_MAIN)
        self._stop_countdown()

    def promptUser(self, connection, is_local, peer):
        # one at a time
        with self._lock:
            # reset state
            if self._tick_thread != None and self._tick_thread.is_alive():
                self._tick_thread.join()
            self._cfg.reload()
            self._tick = int(self._cfg.getSettings(self._cfg.DEFAULT_TIMEOUT_KEY)) if self._cfg.hasKey(self._cfg.DEFAULT_TIMEOUT_KEY) else _constants.DEFAULT_TIMEOUT
            self._tick_thread = threading.Thread(target=self._timeout_worker)
            self._tick_thread.stop = self._ischeckAdvanceded
            self._timeout_triggered = False
            self._rule = None
            self._local = is_local
            self._con = connection

            # XXX: workaround for protobufs that don't report the address of
            # the node. In this case the addr is "unix:/local"
            proto, addr = self._nodes.get_addr(peer)
            self._peer = proto
            if addr != None:
                self._peer = proto+":"+addr

            self._done.clear()
            # trigger and show dialog
            self._prompt_trigger.emit()
            # start timeout thread
            self._tick_thread.start()
            # wait for user choice or timeout
            self._done.wait()

            return self._rule, self._timeout_triggered

    def _timeout_worker(self):
        if self._tick == 0:
            self._timeout_trigger.emit()
            return

        while self._tick > 0 and self._done.is_set() is False:
            t = threading.currentThread()
            # stop only stops the coundtdown, not the thread itself.
            if getattr(t, "stop", True):
                self._tick = int(self._cfg.getSettings(self._cfg.DEFAULT_TIMEOUT_KEY))
                time.sleep(1)
                continue

            self._tick -= 1
            self._tick_trigger.emit()
            time.sleep(1)

        if not self._done.is_set():
            self._timeout_trigger.emit()

    @QtCore.pyqtSlot()
    def on_connection_prompt_triggered(self):
        self.stackedWidget.setCurrentIndex(_constants.PAGE_MAIN)
        self._render_connection(self._con)
        if self._tick > 0:
            self.show()
        # render details after displaying the pop-up.

        self._display_checksums_warning(self._peer, self._con)
        _details.render(self._peer, self.connDetails, self._con)

    @QtCore.pyqtSlot()
    def on_tick_triggered(self):
        self._set_cmd_action_text()

    @QtCore.pyqtSlot()
    def on_timeout_triggered(self):
        self._timeout_triggered = True
        self._send_rule()

    def _hide_widget(self, widget, hide):
        widget.setVisible(not hide)

    def _set_cmd_action_text(self):
        action_idx = self._cfg.getInt(self._cfg.DEFAULT_ACTION_KEY)
        if action_idx == Config.ACTION_ALLOW_IDX:
            self.allowButton.setText("{0} ({1})".format(self._allow_text, self._tick))
            self.allowButton.setIcon(self.allowIcon)
            self.actionButton.setText(self._action_text[Config.ACTION_DENY_IDX])
        else:
            self.allowButton.setText(self._allow_text)
            self.actionButton.setText("{0} ({1})".format(self._action_text[action_idx], self._tick))
            self.actionButton.setIcon(self._action_icon[action_idx])

    def _display_checksums_warning(self, peer, con):
        self.messageLabel.setStyleSheet('')
        self.labelChecksumStatus.setText('')
        is_valid = True
        checksums = con.process_checksums
        expected_list = []

        records = self._rules.get_by_field(peer, "operator_data", con.process_path)

        if records != None and records.first():
            rules_names = []
            while True:
                if not records.next():
                    break
                rule = Rule.new_from_records(records)

                if not rule.enabled:
                    continue
                rules_names.append(rule.name)
                validates, expected = _checksums.verify(checksums, rule)
                if not validates:
                    expected_list.append(expected)
                is_valid &= validates

            if is_valid:
                return ""

            self.messageLabel.setStyleSheet('color: red')
            self.messageLabel.setText(
                QC.translate("popups", "WARNING, bad checksum (<a href='#warning-checksum'>More info</a>)"
                                )
            )
            self.labelChecksumNote.setText(
                QC.translate(
                    "popups",
                    "<font color=\"red\">WARNING, checksums differ for at least one rule.</font><br><br>Current process ({0}):<br>{1}<br><br>Expected from the rule:<br>{2}"
                    .format(
                        con.process_id,
                        checksums[Config.OPERAND_PROCESS_HASH_MD5],
                        expected_list
                    ))
            )

            self.comboChecksumRule.clear()
            self.comboChecksumRule.addItems(rules_names)

            return "<b>WARNING</b><br>bad md5<br>This process:{0}<br>Expected from rule: {1}<br><br>".format(
                checksums[Config.OPERAND_PROCESS_HASH_MD5],
                expected
            )

        return ""

    def _render_connection(self, con):
        app_name, app_icon, description, _ = self._apps_parser.get_info_by_path(con.process_path, "terminal")
        app_args = " ".join(con.process_args)
        _utils.set_app_description(self.appDescriptionLabel, description)
        _utils.set_app_path(self.appPathLabel, app_name, app_args, con)
        _utils.set_app_args(self.argsLabel, app_name, app_args)

        self.checksumLabel.setText(con.process_checksums[Config.OPERAND_PROCESS_HASH_MD5])
        self.checkSum.setChecked(False)

        if app_name == "":
            self.appPathLabel.setVisible(False)
            self.argsLabel.setVisible(False)
            self.argsLabel.setText("")
            app_name = QC.translate("popups", "Unknown process %s" % con.process_path)
            #with self._lock:
            self.appNameLabel.setText(QC.translate("popups", "Outgoing connection"))
        else:
            _utils.set_elide_text(self.appNameLabel, "%s" % app_name, max_size=42)
            self.appNameLabel.setToolTip(app_name)

        # Show process hierarchy (parent and grandparent processes)
        if hasattr(con, 'process_tree') and con.process_tree:
            try:
                # Debug: Print the raw process tree structure
                print(f"[DEBUG] Process tree for {con.process_path}:")
                for i, item in enumerate(con.process_tree):
                    print(f"  [{i}] PID: {item.value}, Path: {item.key}")

                # The tree is already in the correct order (current process first, then parents)
                # We want to show parents, so skip the first entry (current process)
                process_tree = list(con.process_tree)

                # Build hierarchy string (skip current process, show parents)
                hierarchy_parts = []
                for i, item in enumerate(process_tree[1:4]):  # Skip current process, show up to 3 parent levels
                    if i == 0:
                        hierarchy_parts.append(f"Parent: {item.key} (PID: {item.value})")
                    elif i == 1:
                        hierarchy_parts.append(f"Grandparent: {item.key} (PID: {item.value})")
                    else:
                        hierarchy_parts.append(f"Great-grandparent: {item.key} (PID: {item.value})")

                hierarchy_text = " → ".join(hierarchy_parts)

                # Update the app name label to include hierarchy
                if app_name != "":
                    enhanced_name = f"{app_name}\n{hierarchy_text}"
                    _utils.set_elide_text(self.appNameLabel, enhanced_name, max_size=42)
                    self.appNameLabel.setToolTip(enhanced_name)
                else:
                    # For unknown processes, show the hierarchy
                    hierarchy_display = f"Unknown process\n{hierarchy_text}"
                    self.appNameLabel.setText(hierarchy_display)
                    self.appNameLabel.setToolTip(hierarchy_display)

            except Exception as e:
                # If there's an error processing the tree, just continue normally
                print(f"[DEBUG] Error processing process tree: {e}")
                pass

        #if len(self._con.process_args) == 0 or self._con.process_args[0] == "":

        self.cwdLabel.setToolTip("%s %s" % (QC.translate("popups", "Process launched from:"), con.process_cwd))
        _utils.set_elide_text(self.cwdLabel, con.process_cwd, max_size=32)

        pixmap = Icons.get_by_appname(app_icon)
        self.iconLabel.setPixmap(pixmap)

        message = _utils.get_popup_message(self._local, self._peer, app_name, con)

        self.messageLabel.setText(message)
        self.messageLabel.setToolTip(message)

        self.sourceIPLabel.setText(con.src_ip)
        self.destIPLabel.setText(con.dst_ip)
        if con.dst_port == 0:
            self.destPortLabel.setText("")
        else:
            self.destPortLabel.setText(str(con.dst_port))
        self._hide_widget(self.destPortLabel, con.dst_port == 0)
        self._hide_widget(self.checkSum, con.process_checksums[Config.OPERAND_PROCESS_HASH_MD5] == "" or not self._ischeckAdvanceded)
        self._hide_widget(self.checksumLabel, con.process_checksums[Config.OPERAND_PROCESS_HASH_MD5] == "" or not self._ischeckAdvanceded)
        self._hide_widget(self.checksumLabel_2, con.process_checksums[Config.OPERAND_PROCESS_HASH_MD5] == "" or not self._ischeckAdvanceded)
        self._hide_widget(self.destPortLabel_1, con.dst_port == 0)
        self._hide_widget(self.checkDstPort, con.dst_port == 0 or not self._ischeckAdvanceded)

        if self._local:
            try:
                uid = "{0} ({1})".format(con.user_id, pwd.getpwuid(con.user_id).pw_name)
            except:
                uid = ""
        else:
            uid = "{0}".format(con.user_id)

        self.uidLabel.setText(uid)

        self.whatCombo.clear()
        self.whatIPCombo.clear()

        self._add_fixed_options_to_combo(self.whatCombo, con, uid)
        if con.process_path.startswith(_constants.APPIMAGE_PREFIX):
            self._add_appimage_pattern_to_combo(self.whatCombo, con)
        self._add_dst_networks_to_combo(self.whatCombo, con.dst_ip)

        if con.dst_host != "" and con.dst_host != con.dst_ip:
            self._add_dsthost_to_combo(con.dst_host)

        self._add_ip_regexp_to_combo(self.whatCombo, self.whatIPCombo, con)
        self._add_dst_networks_to_combo(self.whatIPCombo, con.dst_ip)

        self._default_action = self._cfg.getInt(self._cfg.DEFAULT_ACTION_KEY)
        _utils.set_default_duration(self._cfg, self.durationCombo)

        _utils.set_default_target(self.whatCombo, con, self._cfg, app_name, app_args)

        self.checkDstIP.setChecked(self._cfg.getBool(self._cfg.DEFAULT_POPUP_ADVANCED_DSTIP))
        self.checkDstPort.setChecked(self._cfg.getBool(self._cfg.DEFAULT_POPUP_ADVANCED_DSTPORT))
        self.checkUserID.setChecked(self._cfg.getBool(self._cfg.DEFAULT_POPUP_ADVANCED_UID))
        self.checkSum.setChecked(self._cfg.getBool(self._cfg.DEFAULT_POPUP_ADVANCED_CHECKSUM))
        if self._cfg.getBool(self._cfg.DEFAULT_POPUP_ADVANCED):
            self.checkAdvanced.toggle()

        self._set_cmd_action_text()
        self.checkAdvanced.setFocus()

        self.setFixedSize(self.size())

        self._post_popup_plugins(con)

    # https://gis.stackexchange.com/questions/86398/how-to-disable-the-escape-key-for-a-dialog
    def keyPressEvent(self, event):
        if not event.key() == QtCore.Qt.Key.Key_Escape:
            super(PromptDialog, self).keyPressEvent(event)

    # prevent a click on the window's x
    # from quitting the whole application
    def closeEvent(self, e):
        self._send_rule()
        e.ignore()

    def close(self):
        self._stop_countdown()
        self._done.set()
        self.hide()

    def _add_fixed_options_to_combo(self, combo, con, uid):
        # the order of these combobox entries must match those in the preferences dialog
        # prefs -> UI -> Default target
        combo.addItem(QC.translate("popups", "from this executable"), _constants.FIELD_PROC_PATH)
        if int(con.process_id) < 0:
            combo.model().item(0).setEnabled(False)

        # Add parent process option if available
        if hasattr(con, 'process_tree') and con.process_tree and len(con.process_tree) > 1:
            parent_path = con.process_tree[1].key
            combo.addItem(QC.translate("popups", "from parent process {0}").format(os.path.basename(parent_path)), _constants.FIELD_PROC_PARENT_PATH)

        # Add grandparent process option if available
        if hasattr(con, 'process_tree') and con.process_tree and len(con.process_tree) > 2:
            grandparent_path = con.process_tree[2].key
            combo.addItem(QC.translate("popups", "from grandparent process {0}").format(os.path.basename(grandparent_path)), _constants.FIELD_PROC_GRANDPARENT_PATH)

        combo.addItem(QC.translate("popups", "from this command line"), _constants.FIELD_PROC_ARGS)

        combo.addItem(QC.translate("popups", "to port {0}").format(con.dst_port), _constants.FIELD_DST_PORT)
        combo.addItem(QC.translate("popups", "to {0}").format(con.dst_ip), _constants.FIELD_DST_IP)

        combo.addItem(QC.translate("popups", "from user {0}").format(uid), _constants.FIELD_USER_ID)
        if int(con.user_id) < 0:
            combo.model().item(4).setEnabled(False)

        combo.addItem(QC.translate("popups", "from this PID"), _constants.FIELD_PROC_ID)

    def _add_ip_regexp_to_combo(self, combo, IPcombo, con):
        IPcombo.addItem(QC.translate("popups", "to {0}").format(con.dst_ip), _constants.FIELD_DST_IP)

        parts = con.dst_ip.split('.')
        nparts = len(parts)
        for i in range(1, nparts):
            combo.addItem(QC.translate("popups", "to {0}.*").format('.'.join(parts[:i])), _constants.FIELD_REGEX_IP)
            IPcombo.addItem(QC.translate("popups", "to {0}.*").format( '.'.join(parts[:i])), _constants.FIELD_REGEX_IP)

    def _add_appimage_pattern_to_combo(self, combo, con):
        """appimages' absolute path usually starts with /tmp/.mount_<
        """
        appimage_bin = os.path.basename(con.process_path)
        appimage_path = os.path.dirname(con.process_path)
        appimage_path = appimage_path[0:len(_constants.APPIMAGE_PREFIX)+6]
        combo.addItem(
            QC.translate("popups", "from {0}*/{1}").format(appimage_path, appimage_bin),
            _constants.FIELD_APPIMAGE
        )

    def _add_dst_networks_to_combo(self, combo, dst_ip):
        alias = NetworkAliases.get_alias(dst_ip)
        if alias:
            combo.addItem(QC.translate("popups", f"to {alias}"), _constants.FIELD_DST_NETWORK)
        if type(ipaddress.ip_address(dst_ip)) == ipaddress.IPv4Address:
            combo.addItem(QC.translate("popups", "to {0}").format(ipaddress.ip_network(dst_ip + "/24", strict=False)),  _constants.FIELD_DST_NETWORK)
            combo.addItem(QC.translate("popups", "to {0}").format(ipaddress.ip_network(dst_ip + "/16", strict=False)),  _constants.FIELD_DST_NETWORK)
            combo.addItem(QC.translate("popups", "to {0}").format(ipaddress.ip_network(dst_ip + "/8", strict=False)),   _constants.FIELD_DST_NETWORK)
        else:
            combo.addItem(QC.translate("popups", "to {0}").format(ipaddress.ip_network(dst_ip + "/64", strict=False)),  _constants.FIELD_DST_NETWORK)
            combo.addItem(QC.translate("popups", "to {0}").format(ipaddress.ip_network(dst_ip + "/128", strict=False)), _constants.FIELD_DST_NETWORK)

    def _add_dsthost_to_combo(self, dst_host):
        self.whatCombo.addItem("%s" % dst_host, _constants.FIELD_DST_HOST)
        self.whatIPCombo.addItem("%s" % dst_host, _constants.FIELD_DST_HOST)

        parts = dst_host.split('.')[1:]
        nparts = len(parts)
        for i in range(0, nparts - 1):
            self.whatCombo.addItem(QC.translate("popups", "to *.{0}").format('.'.join(parts[i:])), _constants.FIELD_REGEX_HOST)
            self.whatIPCombo.addItem(QC.translate("popups", "to *.{0}").format('.'.join(parts[i:])), _constants.FIELD_REGEX_HOST)

    def _on_action_clicked(self, action):
        self._default_action = action
        self._send_rule()

    def _on_deny_btn_clicked(self, action):
        self._default_action = self._cfg.getInt(self._cfg.DEFAULT_ACTION_KEY)
        if self._default_action == Config.ACTION_ALLOW_IDX:
            self._default_action = Config.ACTION_DENY_IDX
        self._send_rule()

    def _is_list_rule(self):
        return self.checkUserID.isChecked() or \
            self.checkDstPort.isChecked() or \
            self.checkDstIP.isChecked() or \
            self.checkSum.isChecked()

    def _extract_all_criteria(self, con):
        """Extract ALL available operands from a connection for storage with the rule."""
        criteria = {}

        # Process information
        criteria['process_path'] = con.process_path if hasattr(con, 'process_path') else ''
        criteria['process_args'] = ' '.join(con.process_args) if hasattr(con, 'process_args') and con.process_args else ''
        criteria['user_id'] = str(con.user_id) if hasattr(con, 'user_id') else ''

        # Process hierarchy
        if hasattr(con, 'process_tree') and con.process_tree:
            if len(con.process_tree) > 1:
                criteria['process_parent_path'] = con.process_tree[1].key
            if len(con.process_tree) > 2:
                criteria['process_grandparent_path'] = con.process_tree[2].key

        # Network information
        criteria['dst_ip'] = con.dst_ip if hasattr(con, 'dst_ip') else ''
        criteria['dst_port'] = str(con.dst_port) if hasattr(con, 'dst_port') else ''
        criteria['dst_host'] = con.dst_host if hasattr(con, 'dst_host') else ''

        return criteria

    def _send_rule(self):
        try:
            self._cfg.setSettings("promptDialog/geometry", self.saveGeometry())
            self._rule = ui_pb2.Rule(name="user.choice")
            self._rule.created = int(datetime.now().timestamp())
            self._rule.enabled = True
            self._rule.duration = _utils.get_duration(self.durationCombo.currentIndex())

            self._rule.action = Config.ACTION_ALLOW
            if self._default_action == Config.ACTION_DENY_IDX:
                self._rule.action = Config.ACTION_DENY
            elif self._default_action == Config.ACTION_REJECT_IDX:
                self._rule.action = Config.ACTION_REJECT

            what_idx = self.whatCombo.currentIndex()
            self._rule.operator.type, self._rule.operator.operand, self._rule.operator.data = _utils.get_combo_operator(
                self.whatCombo.itemData(what_idx),
                self.whatCombo.currentText(),
                self._con)
            if self._rule.operator.data == "":
                print("popups: Invalid rule, discarding: ", self._rule)
                self._rule = None
                return

            rule_temp_name = _utils.get_rule_name(self._rule, self._is_list_rule())
            self._rule.name = rule_temp_name

            # Extract all available criteria for storage with the rule
            all_criteria = self._extract_all_criteria(self._con)

            # Store available operands as a custom attribute for now
            # This will be handled in the add_rules method
            if all_criteria:
                self._rule.available_operands = json.dumps(all_criteria)

            # TODO: move to a method
            data=[]

            alias_selected = False

            if self.whatCombo.itemData(what_idx) == _constants.FIELD_DST_NETWORK:
                alias = NetworkAliases.get_alias(self._con.dst_ip)
                if alias:
                    _type, _operand, _data = Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_PATH, self._con.process_path
                    data.append({"type": _type, "operand": _operand, "data": _data})
                    rule_temp_name = slugify(f"{rule_temp_name} {os.path.basename(self._con.process_path)}")
                    alias_selected = True

            if self.checkDstIP.isChecked() and self.whatCombo.itemData(what_idx) != _constants.FIELD_DST_IP:
                _type, _operand, _data = _utils.get_combo_operator(
                    self.whatIPCombo.itemData(self.whatIPCombo.currentIndex()),
                    self.whatIPCombo.currentText(),
                    self._con)
                data.append({"type": _type, "operand": _operand, "data": _data})
                rule_temp_name = slugify("%s %s" % (rule_temp_name, _data))

            if self.checkDstPort.isChecked() and self.whatCombo.itemData(what_idx) != _constants.FIELD_DST_PORT:
                data.append({"type": Config.RULE_TYPE_SIMPLE, "operand": Config.OPERAND_DEST_PORT, "data": str(self._con.dst_port)})
                rule_temp_name = slugify("%s %s" % (rule_temp_name, str(self._con.dst_port)))

            if self.checkUserID.isChecked() and self.whatCombo.itemData(what_idx) != _constants.FIELD_USER_ID:
                data.append({"type": Config.RULE_TYPE_SIMPLE, "operand": Config.OPERAND_USER_ID, "data": str(self._con.user_id)})
                rule_temp_name = slugify("%s %s" % (rule_temp_name, str(self._con.user_id)))

            if self.checkSum.isChecked() and self.checksumLabel.text() != "":
                _type, _operand, _data = Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_HASH_MD5, self.checksumLabel.text()
                data.append({"type": _type, "operand": _operand, "data": _data})
                rule_temp_name = slugify("%s %s" % (rule_temp_name, _operand))

            is_list_rule = self._is_list_rule()

            # If the user has selected to filter by cmdline, but the launched
            # command path is not absolute or the first component contains
            # "/proc/" (/proc/self/fd.., /proc/1234/fd...), we can't trust it.
            # In these cases, also filter by the absolute path to the binary.
            if self._rule.operator.operand == Config.OPERAND_PROCESS_COMMAND:
                proc_args = " ".join(self._con.process_args)
                proc_args = proc_args.split(" ")
                if os.path.isabs(proc_args[0]) == False or proc_args[0].startswith("/proc"):
                    is_list_rule = True
                    data.append({"type": Config.RULE_TYPE_SIMPLE, "operand": Config.OPERAND_PROCESS_PATH, "data": str(self._con.process_path)})

            if is_list_rule or alias_selected:
                data.append({
                    "type": self._rule.operator.type,
                    "operand": self._rule.operator.operand,
                    "data": self._rule.operator.data
                })
                # We need to send back the operator list to the AskRule() call
                # as json string, in order to add it to the DB.
                self._rule.operator.data = json.dumps(data)
                self._rule.operator.type = Config.RULE_TYPE_LIST
                self._rule.operator.operand = Config.RULE_TYPE_LIST
                for op in data:
                    self._rule.operator.list.extend([
                        ui_pb2.Operator(
                            type=op['type'],
                            operand=op['operand'],
                            sensitive=False if op.get('sensitive') == None else op['sensitive'],
                            data="" if op.get('data') == None else op['data']
                        )
                    ])

            exists = self._rules.exists(self._rule, self._peer)
            if not exists:
                self._rule.name = self._rules.new_unique_name(rule_temp_name, self._peer, "")

            self.hide()
            if self._ischeckAdvanceded:
                self.checkAdvanced.toggle()
            self._ischeckAdvanceded = False

        except Exception as e:
            print("[pop-up] exception creating a rule:", e)
        finally:
            # signal that the user took a decision and
            # a new rule is available
            self._done.set()
            self.hide()
