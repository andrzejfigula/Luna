"""
phone_link.py — BlueZ and obexd over D-Bus: pairing a phone (Agent1), its SMS
(MAP: org.bluez.obex.MessageAccess1) and address book (PBAP). phone.py is the logic.

Everything but the agent runs on phone.py's one worker thread, on private
connections without a main loop; the agent has its own, served by a GLib thread.

The phone is deliberately not Trusted: BlueZ then asks the agent about every
service it opens, and audio is refused, so it can't take over from her speaker.
MAP and PBAP are connections from here to the phone, which need no asking.

dbus and gi are imported on first use (the tests run on Windows without them).
The message formats below them are plain text and need neither.
"""

import functools
import os
import quopri
import re
import subprocess
import threading
import time

BLUEZ = "org.bluez"
OBEX = "org.bluez.obex"
AGENT_IFACE = "org.bluez.Agent1"
AGENT_PATH = "/luna/phone_agent"
PROPS = "org.freedesktop.DBus.Properties"
MNS_UUID = "00001133-0000-1000-8000-00805f9b34fb"   # the phone telling us "a new message"
_NOT_THERE = ("org.freedesktop.DBus.Error.ServiceUnknown",
              "org.freedesktop.DBus.Error.NameHasNoOwner",
              "org.freedesktop.systemd1.NoSuchUnit")


class NoDbus(Exception):
    """python3-dbus / python3-gi can't be imported."""


class NoObex(Exception):
    """bluez-obexd isn't installed."""


class LinkError(Exception):
    """The phone is out of range, or refused."""


# ── the message formats ───────────────────────────────────────────────

def bmessage(number, body):
    """An outgoing SMS as MAP's bMessage. LENGTH counts the MSG block in bytes."""
    number = re.sub(r"[^\d+]", "", number)
    block = f"BEGIN:MSG\r\n{body}\r\nEND:MSG\r\n"
    length = len(block.encode("utf-8"))
    return ("BEGIN:BMSG\r\nVERSION:1.0\r\nSTATUS:READ\r\nTYPE:SMS_GSM\r\n"
            "FOLDER:telecom/msg/OUTBOX\r\nBEGIN:BENV\r\n"
            f"BEGIN:VCARD\r\nVERSION:2.1\r\nFN:\r\nN:\r\nTEL:{number}\r\nEND:VCARD\r\n"
            f"BEGIN:BBODY\r\nCHARSET:UTF-8\r\nLENGTH:{length}\r\n"
            f"{block}END:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n")


def bmessage_body(raw):
    """The text of a received bMessage (a long SMS: its parts joined), or ""."""
    parts = re.findall(r"BEGIN:MSG\r?\n(.*?)\r?\nEND:MSG", raw, re.S)
    return "".join(parts).strip()


def _vcard_value(line):
    head, _, value = line.partition(":")
    if "QUOTED-PRINTABLE" in head.upper():
        try:
            return quopri.decodestring(value.encode("ascii", "ignore")).decode("utf-8", "replace")
        except ValueError:
            return value
    return value


def parse_vcards(raw):
    """[(name, number)] of an address book; one line per person, a mobile first."""
    out = []
    for card in re.findall(r"BEGIN:VCARD(.*?)END:VCARD", raw, re.S | re.I):
        name, cell, other = "", None, None
        for line in card.splitlines():
            key = line.split(":", 1)[0].split(";", 1)[0].upper()
            if key == "FN":
                name = _vcard_value(line).strip()
            elif key == "TEL":
                value = _vcard_value(line).strip()
                if "CELL" in line.split(":", 1)[0].upper():
                    cell = cell or value
                else:
                    other = other or value
        if name and (cell or other):
            out.append((name, cell or other))
    return out


def service_allowed(uuid, is_phone, paired):
    """May this device open this service here? Her phone only tells us about new
    messages (no audio); another device is fine if someone paired it (her speaker)."""
    return uuid.lower() == MNS_UUID if is_phone else bool(paired)


# ── D-Bus ─────────────────────────────────────────────────────────────

_system = _session = None
_agent_bus = _agent = None
_loop_on = False
_handlers = {}


def _dbus():
    try:
        import dbus
        return dbus
    except ImportError as e:
        raise NoDbus(str(e))


def _guarded(fn):
    """A D-Bus error from BlueZ comes out as LinkError."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        dbus = _dbus()
        try:
            return fn(*a, **k)
        except dbus.DBusException as e:
            raise LinkError(e.get_dbus_name())
    return wrapper


def _py(v):
    dbus = _dbus()
    if isinstance(v, dbus.Boolean):
        return bool(v)
    if isinstance(v, (dbus.String, dbus.ObjectPath)):
        return str(v)
    if isinstance(v, (dbus.Byte, dbus.Int16, dbus.UInt16, dbus.Int32, dbus.UInt32, dbus.Int64, dbus.UInt64)):
        return int(v)
    return v


def _props(d):
    return {str(k): _py(v) for k, v in d.items()}


def _sys():
    global _system
    if _system is None:
        _system = _dbus().SystemBus(private=True)
    return _system


def _ses():
    global _session
    if _session is None:
        os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")
        _session = _dbus().SessionBus(private=True)
    return _session


def _iface(bus, name, path, iface):
    return _dbus().Interface(bus.get_object(name, path), iface)


def _objects():
    return _iface(_sys(), BLUEZ, "/", "org.freedesktop.DBus.ObjectManager").GetManagedObjects()


def _adapter():
    for path, ifaces in _objects().items():
        if "org.bluez.Adapter1" in ifaces:
            return str(path)
    raise LinkError("no adapter")


def _addr_of(device_path):
    return str(device_path).rsplit("dev_", 1)[-1].replace("_", ":")


@_guarded
def devices():
    """{address: {"name", "paired"}} of the devices BlueZ knows."""
    out = {}
    for ifaces in _objects().values():
        d = ifaces.get("org.bluez.Device1")
        if d:
            out[str(d["Address"])] = {"name": str(d.get("Alias") or d.get("Name") or ""),
                                      "paired": bool(d.get("Paired"))}
    return out


@_guarded
def open_window(secs):
    """Visible to phones for `secs`, under her own name."""
    dbus = _dbus()
    props = _iface(_sys(), BLUEZ, _adapter(), PROPS)
    props.Set("org.bluez.Adapter1", "Alias", dbus.String("Luna", variant_level=1))
    props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True, variant_level=1))
    props.Set("org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(secs, variant_level=1))
    props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True, variant_level=1))


@_guarded
def close_window():
    dbus = _dbus()
    _iface(_sys(), BLUEZ, _adapter(), PROPS).Set(
        "org.bluez.Adapter1", "Discoverable", dbus.Boolean(False, variant_level=1))


@_guarded
def forget(addr):
    """Remove this device's pairing from BlueZ (and only this one's)."""
    adapter = _adapter()
    path = f"{adapter}/dev_{addr.replace(':', '_')}"
    _iface(_sys(), BLUEZ, adapter, "org.bluez.Adapter1").RemoveDevice(path)


# ── the agent ─────────────────────────────────────────────────────────

def _make_agent(bus):
    dbus = _dbus()
    import dbus.service
    from gi.repository import GLib

    class Rejected(dbus.DBusException):
        _dbus_error_name = "org.bluez.Error.Rejected"

    def asking(device, code, ok, err):
        def answer(yes):                           # any thread; the reply goes out on the loop's
            GLib.idle_add(lambda: (ok() if yes else err(Rejected("no"))) and False)
        name = _device_name(device)
        _handlers["confirm"](_addr_of(device), name, code, answer)

    class Agent(dbus.service.Object):
        @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
        def Release(self):
            pass

        @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
        def AuthorizeService(self, device, uuid):
            addr = _addr_of(device)
            if not service_allowed(str(uuid), _handlers["is_phone"](addr), _device_paired(device)):
                print(f"[phone] refused a service for {addr}: {uuid}", flush=True)
                raise Rejected("no")

        @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="s")
        def RequestPinCode(self, device):
            raise Rejected("no")

        @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
        def DisplayPinCode(self, device, pincode):
            raise Rejected("no")

        @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="u")
        def RequestPasskey(self, device):
            raise Rejected("no")

        @dbus.service.method(AGENT_IFACE, in_signature="ouq", out_signature="")
        def DisplayPasskey(self, device, passkey, entered):
            pass

        @dbus.service.method(AGENT_IFACE, in_signature="ou", out_signature="",
                             async_callbacks=("ok", "err"))
        def RequestConfirmation(self, device, passkey, ok, err):
            asking(device, f"{int(passkey):06d}", ok, err)

        @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="",
                             async_callbacks=("ok", "err"))
        def RequestAuthorization(self, device, ok, err):
            asking(device, None, ok, err)

        @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
        def Cancel(self):
            _handlers["cancel"]()

    return Agent(bus, AGENT_PATH)


def _device_prop(device, prop):
    return _iface(_agent_bus, BLUEZ, device, PROPS).Get("org.bluez.Device1", prop)


def _device_name(device):
    try:
        return str(_device_prop(device, "Alias"))
    except Exception:
        return ""


def _device_paired(device):
    try:
        return bool(_device_prop(device, "Paired"))
    except Exception:
        return False


@_guarded
def register_agent(confirm, cancel, is_phone):
    """The default agent: confirm(addr, name, code, answer) when a device asks to
    pair (answer(True/False), from any thread), cancel() when it gave up,
    is_phone(addr) for what it may open. Raises NoDbus."""
    global _agent, _agent_bus, _loop_on
    _handlers.update(confirm=confirm, cancel=cancel, is_phone=is_phone)
    dbus = _dbus()
    try:
        import dbus.mainloop.glib
        from gi.repository import GLib
    except ImportError as e:
        raise NoDbus(str(e))
    if not _loop_on:
        dbus.mainloop.glib.threads_init()
        threading.Thread(target=GLib.MainLoop().run, daemon=True, name="phone-dbus").start()
        _loop_on = True
    if _agent is None:
        _agent_bus = dbus.SystemBus(private=True, mainloop=dbus.mainloop.glib.DBusGMainLoop())
        _agent = _make_agent(_agent_bus)
    manager = _iface(_agent_bus, BLUEZ, "/org/bluez", "org.bluez.AgentManager1")
    try:
        manager.RegisterAgent(AGENT_PATH, "DisplayYesNo")
    except dbus.DBusException as e:
        if "AlreadyExists" not in e.get_dbus_name():
            raise LinkError(e.get_dbus_name())
    manager.RequestDefaultAgent(AGENT_PATH)


def unregister_agent():
    if _agent is None:
        return
    dbus = _dbus()
    try:
        _iface(_agent_bus, BLUEZ, "/org/bluez", "org.bluez.AgentManager1").UnregisterAgent(AGENT_PATH)
    except dbus.DBusException:
        pass


# ── messages and the address book ─────────────────────────────────────

def _tmp():
    """Files with someone's messages live here: in memory, ours alone."""
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "luna-phone")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


@_guarded
def has_obex():
    """Is obexd installed? Asks the session bus; Bluetooth isn't touched."""
    bus = _iface(_ses(), "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")
    return OBEX in bus.ListActivatableNames() or bool(bus.NameHasOwner(OBEX))


_reloaded = False


def _reload_user_units():
    """obexd just installed: the user's systemd hasn't seen its unit yet (once a run)."""
    global _reloaded
    if _reloaded:
        return
    _reloaded = True
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=15, capture_output=True)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[phone] daemon-reload: {type(e).__name__}", flush=True)


def _create(addr, target):
    dbus = _dbus()
    try:
        client = _iface(_ses(), OBEX, "/org/bluez/obex", "org.bluez.obex.Client1")
        args = dbus.Dictionary({"Target": target}, signature="sv")
        return str(client.CreateSession(addr, args, timeout=70))    # (the phone may be asking)
    except dbus.DBusException as e:
        if e.get_dbus_name() == "org.freedesktop.systemd1.NoSuchUnit":
            _reload_user_units()
        if e.get_dbus_name() in _NOT_THERE:
            raise NoObex(e.get_dbus_name())
        raise LinkError(f"{e.get_dbus_name()}: {str(e.get_dbus_message())[:80]}")


def close(session):
    if not session:
        return
    dbus = _dbus()
    try:
        _iface(_ses(), OBEX, "/org/bluez/obex", "org.bluez.obex.Client1").RemoveSession(session)
    except dbus.DBusException:
        pass


def _wait(transfer, timeout=25):
    """Until the transfer ends. It goes from the bus when it's complete, so a
    missing object isn't an error."""
    dbus = _dbus()
    end = time.time() + timeout
    props = _iface(_ses(), OBEX, transfer, PROPS)
    while time.time() < end:
        try:
            status = str(props.Get("org.bluez.obex.Transfer1", "Status"))
        except dbus.DBusException:
            return
        if status == "complete":
            return
        if status == "error":
            raise LinkError("transfer failed")
        time.sleep(0.15)
    raise LinkError("transfer timed out")


def open_map(addr):
    """A message session with the phone; its path. Raises NoObex or LinkError."""
    dbus = _dbus()
    session = _create(addr, "map")
    try:
        _iface(_ses(), OBEX, session, "org.bluez.obex.MessageAccess1").SetFolder("telecom/msg")
    except dbus.DBusException as e:
        close(session)
        raise LinkError(e.get_dbus_name())
    return session


def _listed(rows):
    """ListMessages' a{oa{sv}}: path -> properties, into a row per message."""
    pairs = rows.items() if hasattr(rows, "items") else rows
    return [dict(_props(p), path=str(path)) for path, p in pairs]


def list_messages(session, count=40):
    """The inbox, as obexd gives it: [{"path", "Subject", "Timestamp", "Sender",
    "SenderAddress", "Type", "Read", …}]. Reading the list marks nothing as read."""
    dbus = _dbus()
    try:
        rows = _iface(_ses(), OBEX, session, "org.bluez.obex.MessageAccess1").ListMessages(
            "inbox", dbus.Dictionary({"MaxCount": dbus.UInt16(count), "SubjectLength": dbus.Byte(255)},
                                     signature="sv"), timeout=25)
    except dbus.DBusException as e:
        raise LinkError(e.get_dbus_name())
    return _listed(rows)


def get_body(path):
    """A message's whole text. (The phone counts this as reading it.)"""
    dbus = _dbus()
    name = os.path.join(_tmp(), "message")
    try:
        transfer, _ = _iface(_ses(), OBEX, path, "org.bluez.obex.Message1").Get(name, False, timeout=25)
        _wait(transfer)
        with open(name, encoding="utf-8", errors="replace", newline="") as f:
            return bmessage_body(f.read())
    except (dbus.DBusException, OSError) as e:
        raise LinkError(str(e))
    finally:
        try:
            os.remove(name)
        except OSError:
            pass


def mark_read(path):
    dbus = _dbus()
    try:
        _iface(_ses(), OBEX, path, PROPS).Set("org.bluez.obex.Message1", "Read",
                                              dbus.Boolean(True, variant_level=1))
    except dbus.DBusException as e:
        raise LinkError(e.get_dbus_name())


def push_message(session, bmsg):
    """Hand an SMS to the phone, which sends it and keeps it among its sent ones."""
    dbus = _dbus()
    name = os.path.join(_tmp(), "outgoing")
    try:
        with open(name, "w", encoding="utf-8", newline="") as f:
            f.write(bmsg)
        args = dbus.Dictionary({"Charset": "utf8", "Transparent": dbus.Boolean(False),
                                "Retry": dbus.Boolean(True)}, signature="sv")
        transfer, _ = _iface(_ses(), OBEX, session, "org.bluez.obex.MessageAccess1").PushMessage(
            name, "outbox", args, timeout=25)
        _wait(transfer)
    except (dbus.DBusException, OSError) as e:
        raise LinkError(str(e))
    finally:
        try:
            os.remove(name)
        except OSError:
            pass


def pull_book(addr):
    """[(name, number)] of the phone's address book. The phone may ask first."""
    dbus = _dbus()
    session = _create(addr, "pbap")
    name = os.path.join(_tmp(), "book")
    try:
        book = _iface(_ses(), OBEX, session, "org.bluez.obex.PhonebookAccess1")
        book.Select("int", "pb")
        args = dbus.Dictionary({"Format": "vcard30",
                                "Fields": dbus.Array(["VERSION", "N", "FN", "TEL"], signature="s")},
                               signature="sv")
        transfer, _ = book.PullAll(name, args, timeout=30)
        _wait(transfer, timeout=90)
        with open(name, encoding="utf-8", errors="replace", newline="") as f:
            return parse_vcards(f.read())
    except (dbus.DBusException, OSError) as e:
        raise LinkError(str(e))
    finally:
        close(session)
        try:
            os.remove(name)
        except OSError:
            pass
