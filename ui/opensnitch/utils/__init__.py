
from PyQt6 import QtCore, QtWidgets, QtGui
from opensnitch.version import version as gui_version, get_version_string
from opensnitch.database import Database
from opensnitch.config import Config
from opensnitch.utils.themes import Themes
from opensnitch.desktop_parser import LinuxDesktopParser
from threading import Thread, Event
import pwd
import socket
import fcntl
import struct
import array
import os, os.path, sys, glob
import enum
import re

class AsnDB():
    __instance = None
    asndb = None

    @staticmethod
    def instance():
        if AsnDB.__instance == None:
            AsnDB.__instance = AsnDB()
        return AsnDB.__instance

    def __init__(self):
        self.ASN_AVAILABLE = True
        self.load()

    def is_available(self):
        return self.ASN_AVAILABLE

    def load(self):
        """Load the ASN DB from disk.

        It'll try to load it from user's opensnitch directory if these file exist:
            - ~/.config/opensnitch/ipasn_db.dat.gz
            - ~/.config/opensnitch/asnames.json
        Otherwise it'll try to load it from python3-pyasn package.
        """
        try:
            if self.asndb != None:
                return

            import pyasn

            IPASN_DB_PATH = os.path.expanduser('~/.config/opensnitch/ipasn_db.dat.gz')
            # .gz not supported for asnames
            AS_NAMES_FILE_PATH = os.path.expanduser('~/.config/opensnitch/asnames.json')

            # if the user hasn't downloaded an updated ipasn db, use the one
            # shipped with the python3-pyasn package
            if os.path.isfile(IPASN_DB_PATH) == False:
                IPASN_DB_PATH = '/usr/lib/python3/dist-packages/data/ipasn_20140513_v12.dat.gz'
            if os.path.isfile(AS_NAMES_FILE_PATH) == False:
                AS_NAMES_FILE_PATH = '/usr/lib/python3/dist-packages/data/asnames.json'

            print("using IPASN DB:", IPASN_DB_PATH)
            self.asndb = pyasn.pyasn(IPASN_DB_PATH, as_names_file=AS_NAMES_FILE_PATH)
        except Exception as e:
            self.ASN_AVAILABLE = False
            print("exception loading ipasn db:", e)
            print("Install python3-pyasn to display IP's network name.")


    def lookup(self, ip):
        """Lookup the IP in the ASN DB.

        Return the net range and the prefix if found, otherwise nothing.
        """
        try:
            return self.asndb.lookup(ip)
        except Exception:
            return "", ""

    def get_as_name(self, asn):
        """Get the ASN name given a network range.

        Return the name of the network if found, otherwise nothing.
        """
        try:
            asname = self.asndb.get_as_name(asn)
            if asname == None:
                asname = ""
            return asname
        except Exception:
            return ""

    def get_asn(self, ip):
        try:
            asn, prefix = self.lookup(ip)
            return self.get_as_name(asn)
        except Exception:
            return ""

class GenericTimer(Thread):
    interval = 1
    stop_flag = None
    callback = None

    def __init__(self, _interval, _in_loop, _callback, _args=()):
        Thread.__init__(self, name="generic_timer_thread")
        self.interval = _interval
        self.in_loop = _in_loop
        self.stop_flag = Event()
        self.callback = _callback
        self.args = _args

    def run(self):
        if self.in_loop:
            while not self.stop_flag.wait(self.interval):
                self.callback(self.args)
            return

        if self.stop_flag.wait(self.interval):
            return
        self.callback(self.args)

    def stop(self):
        self.stop_flag.set()

class OneshotTimer(GenericTimer):
    def __init__(self, _interval, _callback, _args=()):
        GenericTimer.__init__(self, _interval, False, _callback, _args)

    def run(self):
        self.stop_flag.wait(self.interval)
        if self.stop_flag.is_set():
            return
        self.callback(self.args)
        self.stop()

    def stop(self):
        self.stop_flag.set()

class CleanerTask(Thread):
    interval = 1
    stop_flag = None
    callback = None

    def __init__(self, _interval, _callback):
        Thread.__init__(self, name="cleaner_db_thread")
        self.interval = _interval * 60
        self.stop_flag = Event()
        self.callback = _callback
        self._cfg = Config.init()

        # We need to instantiate a new QsqlDatabase object with a unique name,
        # because it's not thread safe:
        # "A connection can only be used from within the thread that created it."
        # https://doc.qt.io/qt-5/threads-modules.html#threads-and-the-sql-module
        # The filename and type is the same, the one chosen by the user.
        self.db = Database("db-cleaner-connection")
        self.db_status, db_error = self.db.initialize(
            dbtype=self._cfg.getInt(self._cfg.DEFAULT_DB_TYPE_KEY),
            dbfile=self._cfg.getSettings(self._cfg.DEFAULT_DB_FILE_KEY),
            dbjrnl_wal=self._cfg.getBool(self._cfg.DEFAULT_DB_JRNL_WAL)
        )

    def run(self):
        if self.db_status == False:
            return
        while not self.stop_flag.is_set():
            self.stop_flag.wait(self.interval)
            self.callback(self.db)

    def stop(self):
        self.stop_flag.set()
        self.db.close()

class QuickHelp():
    @staticmethod
    def show(help_str):
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), help_str)

class Utils():
    @staticmethod
    def check_versions(daemon_version):
        lMayor, lMinor, lPatch = gui_version.split(".")
        rMayor, rMinor, rPatch = daemon_version.split(".")
        return lMayor != rMayor or (lMayor == rMayor and lMinor != rMinor)

    @staticmethod
    def get_user_id(uid):
        pw_name = uid
        try:
            pw_name = pwd.getpwuid(int(uid)).pw_name + " (" + uid + ")"
        except Exception:
            #pw_name += " (error)"
            pass

        return pw_name

    @staticmethod
    def get_interfaces():
        max_possible = 128  # arbitrary. raise if needed.
        bytes = max_possible * 32
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        names = array.array('B', b'\0' * bytes)
        outbytes = struct.unpack('iL', fcntl.ioctl(
            s.fileno(),
            0x8912,  # SIOCGIFCONF
            struct.pack('iL', bytes, names.buffer_info()[0])
        ))[0]
        return names.tobytes(), outbytes

    @staticmethod
    def create_socket_dirs():
        """https://www.linuxbase.org/betaspecs/fhs/fhs.html#runRuntimeVariableData
        """
        run_path = "/run/user/{0}".format(os.getuid())
        var_run_path = "/var{0}".format(run_path)

        try:
            if os.path.exists(run_path):
                os.makedirs(run_path + "/opensnitch/", 0o700)
            if os.path.exists(var_run_path):
                os.makedirs(var_run_path + "/opensnitch/", 0o700)
        except:
            pass

class Message():

    @staticmethod
    def ok(title, message, icon):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setWindowFlags(msgBox.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        msgBox.setText("<b>{0}</b><br><br>{1}".format(title, message))
        msgBox.setIcon(icon)
        msgBox.setModal(True)
        msgBox.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        msgBox.exec()

    @staticmethod
    def yes_no(title, message, icon):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setWindowFlags(msgBox.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        msgBox.setText(title)
        msgBox.setIcon(icon)
        msgBox.setModal(True)
        msgBox.setInformativeText(message)
        msgBox.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Cancel | QtWidgets.QMessageBox.StandardButton.Yes)
        msgBox.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        return msgBox.exec()

class FileDialog():

    @staticmethod
    def save(parent):
        options = QtWidgets.QFileDialog.Options()
        fileName, _ = QtWidgets.QFileDialog.getSaveFileName(parent, "", "","All Files (*)", options=options)
        return fileName

    @staticmethod
    def select(parent):
        options = QtWidgets.QFileDialog.Options()
        fileName, _ = QtWidgets.QFileDialog.getOpenFileName(parent, "", "","All Files (*)", options=options)
        return fileName

    @staticmethod
    def select_dir(parent, current_dir):
        options = QtWidgets.QFileDialog.Options()
        fileName = QtWidgets.QFileDialog.getExistingDirectory(parent, "", current_dir, options)
        return fileName

# https://stackoverflow.com/questions/29503339/how-to-get-all-values-from-python-enum-class
class Enums(enum.Enum):
    @classmethod
    def to_dict(cls):
        return {e.name: e.value for e in cls}

    @classmethod
    def keys(cls):
        return cls._member_names_

    @classmethod
    def values(cls):
        return [str(v.value) for v in cls]

class NetworkInterfaces():
    # https://gist.github.com/pklaus/289646
    @staticmethod
    def list():
        namestr, outbytes = Utils.get_interfaces()
        _interfaces = {}
        for i in range(0, outbytes, 40):
            try:
                name = namestr[i:i+16].split(b'\0', 1)[0]
                addr = namestr[i+20:i+24]
                _interfaces[name.decode()] = "%d.%d.%d.%d" % (int(addr[0]), int(addr[1]), int(addr[2]), int(addr[3]))
            except Exception as e:
                print("utils.NetworkInterfaces() exception:", e)

        return _interfaces



class NetworkServices():
    """Get a list of known ports. /etc/services
    """
    __instance = None

    @staticmethod
    def instance():
        if NetworkServices.__instance == None:
            NetworkServices.__instance = NetworkServices()
        return NetworkServices.__instance

    srv_array = []
    ports_list = []

    def __init__(self):
        etcServicesPath = "/etc/services"
        if not os.path.isfile(etcServicesPath) and os.path.isfile("/usr/etc/services"):
            etcServicesPath = "/usr/etc/services"

        try:
            etcServices = open(etcServicesPath)
            for line in etcServices:
                if line[0] == "#":
                    continue
                g = re.search(r'([a-zA-Z0-9\-]+)( |\t)+([0-9]+)\/([a-zA-Z0-9\-]+)(.*)\n', line)
                if g:
                    self.srv_array.append("{0}/{1} {2}".format(
                        g.group(1),
                        g.group(3),
                        "" if len(g.groups())>3 and g.group(4) == "" else "({0})".format(g.group(4).replace("\t", ""))
                    )
                    )
                    self.ports_list.append(g.group(3))

            # extra ports that don't exist in /etc/services
            self.srv_array.append("wireguard/51820 WireGuard VPN")
            self.ports_list.append("51820")
        except Exception as e:
            print("Error loading {0}: {1}".format(etcServicesPath, e))

    def to_array(self):
        return self.srv_array

    def service_by_index(self, idx):
        try:
            return self.srv_array[idx]
        except:
            return ""

    def service_by_name(self, name):
        try:
            return self.srv_array.index(name)
        except:
            return -1

    def port_by_index(self, idx):
        try:
            return self.ports_list[idx]
        except:
            return -1

    def index_by_port(self, port):
        try:
            return self.ports_list.index(str(port))
        except:
            return -1

class Icons():
    """Util to display Qt's built-in icons when the system is not configured as
    we expect. More information:
        https://github.com/evilsocket/opensnitch/wiki/GUI-known-problems#no-icons-on-the-gui
        https://user-images.githubusercontent.com/5894606/82400818-99ef6e80-9a2e-11ea-878d-99e30e13dbdd.jpg
    """

    defaults = {
        'document-new': "SP_FileIcon",
        'document-save': "SP_DialogSaveButton",
        'document-open': "SP_DirOpenIcon",
        'format-justify-fill': "SP_FileDialogDetailedView",
        'preferences-system': "SP_FileDialogListView",
        'preferences-desktop': "SP_FileDialogListView",
        'security-high': "SP_VistaShield",
        'go-previous': "SP_ArrowLeft",
        'go-jump': "SP_CommandLink",
        'go-down': "SP_TitleBarUnshadeButton",
        'go-up': "SP_TitleBarShadeButton",
        'help-browser': "SP_DialogHelpButton",
        'emblem-important': "SP_DialogCancelButton",
        'emblem-default': "SP_DialogApplyButton",
        'window-close': "SP_DialogCloseButton",
        'system-run': "",
        'preferences-system-network': "",
        'document-properties': "",
        'edit-delete': "SP_DialogCancelButton",
        'list-add': "SP_ArrowUp",
        'list-remove': "SP_ArrowDown",
        'system-search': "SP_FileDialogContentsView",
        'application-exit': "SP_TitleBarCloseButton",
        'view-sort-ascending': "SP_ToolBarVerticalExtensionButton",
        'address-book-new': "",
        'media-playback-start': "SP_MediaPlay",
        'media-playback-pause': "SP_MediaPause",
        'system-search': "SP_FileDialogContentsView",
        'accessories-text-editor': "SP_DialogOpenButton",
        'edit-clear-all': "SP_DialogResetButton",
        'reload': "SP_DialogResetButton",
        'dialog-information': "SP_MessageBoxInformation",
        'dialog-warning': "SP_MessageBoxWarning"
    }

    @staticmethod
    def new(widget, icon_name):
        if Themes.IS_DARK:
            icon_pix = os.path.join(
                os.path.abspath(os.path.dirname(__file__)),
                "../res/themes/dark/icons/",
                icon_name + ".svg")
            if os.path.exists(icon_pix):
                icon_image = QtGui.QPixmap(icon_pix)
                icon = QtGui.QIcon()
                icon.addPixmap(icon_image, QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.Off)
                return icon

        icon = QtGui.QIcon.fromTheme(icon_name, QtGui.QIcon.fromTheme(icon_name + "-symbolic"))
        if icon.isNull():
            try:
                icon = widget.style().standardIcon(getattr(QtWidgets.QStyle.StandardPixmap, Icons.defaults[icon_name]))
                # in some DEs, like Enlightenment, some builtins icons may be
                # empty. The icon is not Null, but there're no available sizes,
                # and the pixmap is empty.
                # TODO: Create a default icon, and distribute it as resource.
                if len(icon.availableSizes()) == 0:
                    icon = widget.style().standardIcon(getattr(QtWidgets.QStyle.StandardPixmap, 'SP_FileIcon'))
            except Exception as e:
                print("Qt standardIcon exception:", icon_name, ",", e)

        return icon

    @staticmethod
    def get_by_appname(app_icon):
        """return the pixmap of an application.
        """
        try:
            icon = QtGui.QIcon().fromTheme(app_icon)
            pixmap = icon.pixmap(icon.actualSize(QtCore.QSize(48, 48)))
            if QtGui.QIcon().hasThemeIcon(app_icon) == False or pixmap.height() == 0:
                # sometimes the icon is an absolute path, sometimes it's not
                if os.path.isabs(app_icon):
                    icon = QtGui.QIcon(app_icon)
                    pixmap = icon.pixmap(icon.actualSize(QtCore.QSize(48, 48)))
                else:
                    icon_path = LinuxDesktopParser.discover_app_icon(app_icon)
                    if icon_path != None:
                        icon = QtGui.QIcon(icon_path)
                        pixmap = icon.pixmap(icon.actualSize(QtCore.QSize(48, 48)))
        except Exception as e:
            print("Icons.get_by_appname() exception:", e)

        return pixmap

class Versions():
    @staticmethod
    def get():
        try:
            from google.protobuf import __version__ as proto_version
            from grpc import _grpcio_metadata as grpcmeta

            return get_version_string(), grpcmeta.__version__, proto_version

        except:
            return "none", "none", "none"
