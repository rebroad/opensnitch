from slugify import slugify
import os

from PyQt6.QtCore import QCoreApplication as QC

from opensnitch.config import Config
from opensnitch.dialogs.prompt import _constants

def truncate_text(text, max_size=64):
    if len(text) > max_size:
        text = text[:max_size] + "..."
    return text

def set_elide_text(widget, text, max_size=64):
    text = truncate_text(text, max_size)
    widget.setText(text)

def get_rule_name(rule, is_list):
    rule_temp_name = slugify("%s %s" % (rule.action, rule.duration))
    if is_list:
        rule_temp_name = "%s-list" % rule_temp_name
    else:
        rule_temp_name = "%s-simple" % rule_temp_name
    rule_temp_name = slugify("%s %s" % (rule_temp_name, rule.operator.data))

    return rule_temp_name[:128]

def get_popup_message(is_local, node, app_name, con):
    """
    _get_popup_message helps constructing the message that is displayed on
    the pop-up dialog. Example:
        curl is connecting to www.opensnitch.io on TCP port 443
    """
    app_name = truncate_text(app_name)

    # Add process hierarchy information to the message
    hierarchy_info = ""
    if hasattr(con, 'process_tree') and con.process_tree:
        try:
            process_tree = list(con.process_tree)

            # Show up to 2 levels of hierarchy in the message (skip current process)
            hierarchy_parts = []
            for i, item in enumerate(process_tree[1:3]):  # Skip current process, show up to 2 parent levels
                if i == 0:
                    hierarchy_parts.append(f"Parent: {item.key} (PID: {item.value})")
                elif i == 1:
                    hierarchy_parts.append(f"Grandparent: {item.key} (PID: {item.value})")

            if hierarchy_parts:
                hierarchy_info = f"<br><small>Process hierarchy: {' → '.join(hierarchy_parts)}</small>"
        except Exception:
            pass

    message = "<b>{0}</b>{1}".format(app_name, hierarchy_info)
    if not is_local:
        message = QC.translate("popups", "<b>Remote</b> process {0} running on <b>{1}</b>".format(
            message,
            node.split(':')[1])
        )

    msg_action = QC.translate("popups", "is connecting to <b>{0}</b> on {1} port {2}".format(
        con.dst_host or con.dst_ip,
        con.protocol.upper(),
        con.dst_port )
    )

    # icmp port is 0 (i.e.: no port)
    if con.dst_port == 0:
        msg_action = QC.translate("popups", "is connecting to <b>{0}</b>, {1}".format(
            con.dst_host or con.dst_ip,
            con.protocol.upper() )
        )

    if con.dst_port == 53 and con.dst_ip != con.dst_host and con.dst_host != "":
        msg_action = QC.translate("popups", "is attempting to resolve <b>{0}</b> via {1}, {2} port {3}".format(
            con.dst_host,
            con.dst_ip,
            con.protocol.upper(),
            con.dst_port)
        )

    return "{0} {1}".format(message, msg_action)

def set_app_path(appPathLabel, app_name, app_args, con):
    # show the binary path if it's not part of the cmdline args:
    # cmdline: telnet 1.1.1.1 (path: /usr/bin/telnet.netkit)
    # cmdline: /usr/bin/telnet.netkit 1.1.1.1 (the binary path is part of the cmdline args, no need to display it)
    if con.process_path != "" and len(con.process_args) >= 1 and con.process_path not in con.process_args:
        appPathLabel.setToolTip("Process path: {0}".format(con.process_path))
        if app_name.lower() == app_args:
            set_elide_text(appPathLabel, "%s" % con.process_path)
        else:
            set_elide_text(appPathLabel, "(%s)" % con.process_path)
        appPathLabel.setVisible(True)
    elif con.process_path != "" and len(con.process_args) == 0:
        set_elide_text(appPathLabel, "%s" % con.process_path)
        appPathLabel.setVisible(True)
    else:
        appPathLabel.setVisible(False)
        appPathLabel.setText("")

    appPathLabel.setText(
        "".join(
            filter(str.isprintable, appPathLabel.text())
        )
    )

def set_app_args(argsLabel, app_name, app_args):
    # if the app name and the args are the same, there's no need to display
    # the args label (amule for example)
    if app_name.lower() != app_args:
        argsLabel.setVisible(True)
        set_elide_text(argsLabel, app_args, 256)
        argsLabel.setToolTip(app_args)
    else:
        argsLabel.setVisible(False)
        argsLabel.setText("")

    argsLabel.setText(
        "".join(
            filter(str.isprintable, argsLabel.text())
        )
    )

def set_app_description(appDescriptionLabel, description):
    if description != None and description != "":
        appDescriptionLabel.setVisible(True)
        appDescriptionLabel.setFixedHeight(50)
        appDescriptionLabel.setToolTip(description)
        set_elide_text(appDescriptionLabel, "%s" % description)
    else:
        appDescriptionLabel.setVisible(False)
        appDescriptionLabel.setFixedHeight(0)
        appDescriptionLabel.setText("")

    appDescriptionLabel.setText(
        "".join(
            filter(str.isprintable, appDescriptionLabel.text())
        )
    )

def get_duration(duration_idx):
    if duration_idx == 0:
        return Config.DURATION_ONCE
    elif duration_idx == 1:
        return _constants.DURATION_30s
    elif duration_idx == 2:
        return _constants.DURATION_5m
    elif duration_idx == 3:
        return _constants.DURATION_15m
    elif duration_idx == 4:
        return _constants.DURATION_30m
    elif duration_idx == 5:
        return _constants.DURATION_1h
    elif duration_idx == 6:
        return _constants.DURATION_12h
    elif duration_idx == 7:
        return Config.DURATION_UNTIL_RESTART
    else:
        return Config.DURATION_ALWAYS

def set_default_duration(cfg, durationCombo):
    if cfg.hasKey(Config.DEFAULT_DURATION_KEY):
        cur_idx = cfg.getInt(Config.DEFAULT_DURATION_KEY)
        durationCombo.setCurrentIndex(cur_idx)
    else:
        durationCombo.setCurrentIndex(Config.DEFAULT_DURATION_IDX)

def set_default_target(combo, con, cfg, app_name, app_args):
    # set appimage as default target if the process path starts with
    # /tmp/._mount
    if con.process_path.startswith(_constants.APPIMAGE_PREFIX):
        idx = combo.findData(_constants.FIELD_APPIMAGE)
        if idx != -1:
            combo.setCurrentIndex(idx)
            return

    if int(con.process_id) > 0 and app_name != "" and app_args != "":
        combo.setCurrentIndex(int(cfg.getSettings(cfg.DEFAULT_TARGET_KEY)))
    else:
        combo.setCurrentIndex(2)

def get_combo_operator(data, comboText, con):
    if data == _constants.FIELD_PROC_PATH:
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_PATH, con.process_path

    elif data == _constants.FIELD_PROC_PARENT_PATH:
        # Get parent process path from process tree
        if hasattr(con, 'process_tree') and con.process_tree and len(con.process_tree) > 1:
            parent_path = con.process_tree[1].key  # Second entry is parent
            return Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_PARENT_PATH, parent_path
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_PARENT_PATH, ""

    elif data == _constants.FIELD_PROC_GRANDPARENT_PATH:
        # Get grandparent process path from process tree
        if hasattr(con, 'process_tree') and con.process_tree and len(con.process_tree) > 2:
            grandparent_path = con.process_tree[2].key  # Third entry is grandparent
            return Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_GRANDPARENT_PATH, grandparent_path
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_GRANDPARENT_PATH, ""

    elif data == _constants.FIELD_PROC_ARGS:
        # this should not happen
        if len(con.process_args) == 0 or con.process_args[0] == "":
            return Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_PATH, con.process_path
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_COMMAND, ' '.join(con.process_args)

    elif data == _constants.FIELD_PROC_ID:
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_PROCESS_ID, "{0}".format(con.process_id)

    elif data == _constants.FIELD_USER_ID:
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_USER_ID, "{0}".format(con.user_id)

    elif data == _constants.FIELD_DST_PORT:
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_DEST_PORT, "{0}".format(con.dst_port)

    elif data == _constants.FIELD_DST_IP:
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_DEST_IP, con.dst_ip

    elif data == _constants.FIELD_DST_HOST:
        return Config.RULE_TYPE_SIMPLE, Config.OPERAND_DEST_HOST, comboText

    elif data == _constants.FIELD_DST_NETWORK:
        # strip "to ": "to x.x.x/20" -> "x.x.x/20"
        # we assume that to is one word in all languages
        parts = comboText.split(' ')
        text = parts[len(parts)-1]
        return Config.RULE_TYPE_NETWORK, Config.OPERAND_DEST_NETWORK, text

    elif data == _constants.FIELD_REGEX_HOST:
        parts = comboText.split(' ')
        text = parts[len(parts)-1]
        # ^(|.*\.)yahoo\.com
        dsthost = r'\.'.join(text.split('.')).replace("*", "")
        dsthost = r'^(|.*\.)%s$' % dsthost[2:]
        return Config.RULE_TYPE_REGEXP, Config.OPERAND_DEST_HOST, dsthost

    elif data == _constants.FIELD_REGEX_IP:
        parts = comboText.split(' ')
        text = parts[len(parts)-1]
        return Config.RULE_TYPE_REGEXP, Config.OPERAND_DEST_IP, "%s" % r'\.'.join(text.split('.')).replace("*", ".*")

    elif data == _constants.FIELD_APPIMAGE:
        appimage_bin = os.path.basename(con.process_path)
        appimage_path = os.path.dirname(con.process_path).replace('.', r'\.')
        appimage_path = appimage_path[0:len(_constants.APPIMAGE_PREFIX)+7]
        return Config.RULE_TYPE_REGEXP, Config.OPERAND_PROCESS_PATH, r'^{0}[0-9A-Za-z]{{6,7}}\/.*{1}$'.format(appimage_path, appimage_bin)
