import shutil
import subprocess


DEVICE_PROPERTIES = {
    "ro.product.manufacturer": "manufacturer",
    "ro.product.brand": "brand",
    "ro.product.model": "model",
    "ro.product.device": "device",
    "ro.product.name": "product",
    "ro.product.board": "board",
    "ro.hardware": "hardware",
    "ro.build.version.release": "android_version",
    "ro.build.version.sdk": "sdk",
    "ro.build.display.id": "build",
    "ro.build.version.security_patch": "security_patch",
    "ro.build.fingerprint": "fingerprint",
}


class ADBUnavailable(RuntimeError):
    pass


def scan_devices():
    executable = shutil.which("adb")
    if not executable:
        raise ADBUnavailable("ADB was not found. Install Android Platform Tools and make adb available on PATH.")
    result = subprocess.run(
        [executable, "devices"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "ADB could not list connected devices.")
    devices = []
    for line in result.stdout.splitlines()[1:]:
        columns = line.strip().split()
        if len(columns) >= 2 and columns[1] == "device":
            devices.append(columns[0])
    return devices


def read_properties(serial):
    executable = shutil.which("adb")
    if not executable:
        raise ADBUnavailable("ADB was not found. Install Android Platform Tools and make adb available on PATH.")
    result = subprocess.run(
        [executable, "-s", serial, "shell", "getprop"],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Could not read properties from {serial}.")
    properties = {}
    for line in result.stdout.splitlines():
        if line.startswith("[") and "]: [" in line:
            name, value = line[1:].split("]: [", 1)
            properties[name] = value.rstrip("]")
    normalized = {target: properties.get(source, "") for source, target in DEVICE_PROPERTIES.items()}
    normalized["serial"] = serial
    normalized["properties"] = properties
    return normalized
