from pathlib import Path
import os
import platform
import shutil
from version import __version__  # noqa: F401 (re-exported; single source of truth: version.py)

#  Expert User Settings ! -------------------------------------------------------------------------------------
NIR_CAMERA = "M20_RAW"  # Format of the original near infrared image
VIS_CAMERA = "DJI_RAW"  # Format of the original visible image
CROP = 50       # Final crop after alignment  3992 x 2992 -> 3892 x 2892   (3892 - 2* PRE_CROP)x(2892 - 2* PRE_CROP)
PRE_CROP = 4    # RawTherapee cropping from the original . DNG image   4000 x 3000 -> 3992 x 2992  (4000 - 2* PRE_CROP)x(3000 - 2* PRE_CROP)
VIS_CAMERA_PIX_X = 4000     # Image size (width).  Visible camera (DJI)
VIS_CAMERA_PIX_Y = 3000     # Image size (height). Visible camera (DJI)
VIS_LPIX = 1.6 * 10 ** -6   # Visible camera pixel size. DJI Mavic Air 2.   (1.6 micron meter)
VIS_CAMERA_F_MAX = 2.8  # Maximum aperture
IRD_CAMERA_MAKER = "irdrone"
IRD_CAMERA_MODEL = "multispectral"
IRD_CAMERA_DESCRIPTION = "DJI-FC3170-Mavic_Air_2|SJCAM-M20-SJCam_M20|Kolarivision-720-nm"
IRD_CAMERA_SERIAL_NUMBER = "2022-V001"
IRD_PIX_X = VIS_CAMERA_PIX_X - 2*CROP - 2*PRE_CROP  # Image size (width).  Output from the alignment process
IRD_PIX_Y = VIS_CAMERA_PIX_Y - 2*CROP - 2*PRE_CROP  # Image size (height). Output from the alignment process
IRD_LPIX = VIS_LPIX
IRD_FOCAL_FACTOR = 0.75     # Default value
IRD_FOCAL_LENGTH = 4.6     # Default value
IRD_FOCAL_LENGTH_35MM = 27     # Default value
IRD_FOCAL_LENGTH_PIX = 2898     # Default value
IRD_LENS_INFO = '%s mm f/%s' % (str(round(IRD_FOCAL_LENGTH_35MM, 0)), str(round(VIS_CAMERA_F_MAX,1)))
OVERLAP_X = 0.30    #
OVERLAP_Y = 0.75    # Image Overlay for mapping   [0.50 ; 0.90]
CNIRCVIS_0 = 0.046  # Distance between the lenses of two cameras (DJI Mavic Air 2 and SJCam M20) = 46 mm.


# User Settings --------------------------------------------------------------------------------------
NIR_FILTER_MAKER = 'OpticsConcept'  #
NIR_FILTER_MODEL = 830              # cut wavelength ( in nanometers nm) of the NIR camera filter
COPYRIGHT = "Copyright"
ARTIST = "Artist"

# ------------------------------------------------------
# Working folder (where the missions are stored)
# ------------------------------------------------------
# Chosen in this order:
#   1. environment variable IRDRONE_WORKING_DIR (wins at every launch)
#   2. the folder saved in the user settings file (chosen in the wizard)
#   3. the default: C:/Air-Mission on Windows, ~/Air-Mission elsewhere
# The folder is not created here: set_working_dir() / ensure_working_dir() do it.
import json  # noqa: E402

DEFAULT_WORKING_DIR = Path(r"C:/Air-Mission") if os.name == "nt" else Path.home() / "Air-Mission"


def _settings_file():
    """Per-user settings file, override with IRDRONE_SETTINGS_FILE."""
    if os.environ.get("IRDRONE_SETTINGS_FILE"):
        return Path(os.environ["IRDRONE_SETTINGS_FILE"])
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "IRDrone"
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "IRDrone"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "irdrone"
    return base / "settings.json"


SETTINGS_FILE = _settings_file()


def load_user_settings():
    """Saved user settings (empty dict when missing or unreadable)."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as file:
            settings = json.load(file)
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError):
        return {}


def save_user_settings(**changes):
    """Merge changes into the user settings file."""
    settings = load_user_settings()
    settings.update(changes)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2)


def _resolve_working_dir():
    """(folder, source) with source "environment", "saved" or "default"."""
    if os.environ.get("IRDRONE_WORKING_DIR"):
        return Path(os.environ["IRDRONE_WORKING_DIR"]), "environment"
    saved = load_user_settings().get("working_dir")
    if saved:
        return Path(saved), "saved"
    return DEFAULT_WORKING_DIR, "default"


OUTPUT_FOLDER_NAME, WORKING_DIR_SOURCE = _resolve_working_dir()


def set_working_dir(folder, remember=True):
    """Use folder as the working folder (created if missing) and save it.
    Modules must read config.OUTPUT_FOLDER_NAME when they need it, not copy it
    at import, to see the change."""
    global OUTPUT_FOLDER_NAME, WORKING_DIR_SOURCE
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    OUTPUT_FOLDER_NAME = folder
    if remember:
        save_user_settings(working_dir=str(folder))
        WORKING_DIR_SOURCE = "saved"
    return folder


def ensure_working_dir():
    """Create the current working folder if needed; False if that fails."""
    try:
        OUTPUT_FOLDER_NAME.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


# ------------------------------------------------------
# External tools: ExifTool, RawTherapee, SJCam RAW -> DNG converter
# ------------------------------------------------------
# Each tool is looked up in this order:
#   1. its environment variable (EXIFTOOLPATH, RAWTHERAPEEPATH, SJCONVERTERPATH)
#   2. the usual install location / the copy bundled in thirdparty/
#   3. the PATH
# A missing tool does not stop the import: the path keeps its default value,
# missing_tools() lists what is missing so the caller can tell the user.
REPOSITORY_ROOT = Path(__file__).resolve().parent
THIRDPARTY = REPOSITORY_ROOT / "thirdparty"
IS_WINDOWS = os.name == "nt"


def _windows_rawtherapee_candidates():
    """rawtherapee-cli.exe in Program Files, version 5.8 first, then the newest."""
    candidates = []
    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if base:
            folder = Path(base) / "RawTherapee"
            candidates.append(folder / "5.8" / "rawtherapee-cli.exe")
            candidates.extend(sorted(folder.glob("*/rawtherapee-cli.exe"), reverse=True))
            candidates.append(folder / "rawtherapee-cli.exe")
    candidates.append(Path(r"C:\Program Files\RawTherapee\5.8\rawtherapee-cli.exe"))
    return candidates


def _find_tool(variable, candidates, names):
    """Return (path, found) for an external tool, see the lookup order above."""
    value = os.environ.get(variable)
    if value:
        return value, Path(value).is_file()
    for candidate in candidates:
        if Path(candidate).is_file():
            return str(candidate), True
    for name in names:
        found = shutil.which(name)
        if found:
            return found, True
    default = candidates[0] if candidates else names[0]
    return str(default), False


if IS_WINDOWS:
    _EXIFTOOL = ([THIRDPARTY / "exiftool" / "exiftool.exe"], ["exiftool.exe", "exiftool"])
    _RAWTHERAPEE = (_windows_rawtherapee_candidates(), ["rawtherapee-cli.exe"])
    _SJCONVERTER = ([THIRDPARTY / "sjcam_raw2dng" / "sjcam_raw2dng.exe"], ["sjcam_raw2dng.exe"])
else:
    _EXIFTOOL = ([Path("/usr/bin/exiftool")], ["exiftool"])
    _RAWTHERAPEE = ([Path("/usr/bin/rawtherapee-cli"),
                     Path("/Applications/RawTherapee.app/Contents/MacOS/rawtherapee-cli")],
                    ["rawtherapee-cli"])
    # The bundled Linux converter is an x86-64 binary: no use on ARM or macOS.
    _bundled = THIRDPARTY / "sjcam_raw2dng_linux" / "sjcam_raw2dng"
    _x86_linux = platform.system() == "Linux" and platform.machine().lower() in ("x86_64", "amd64")
    _SJCONVERTER = ([_bundled] if _x86_linux else [], ["sjcam_raw2dng"])

EXIFTOOLPATH, _EXIFTOOL_FOUND = _find_tool("EXIFTOOLPATH", *_EXIFTOOL)
RAWTHERAPEEPATH, _RAWTHERAPEE_FOUND = _find_tool("RAWTHERAPEEPATH", *_RAWTHERAPEE)
SJCONVERTERPATH, _SJCONVERTER_FOUND = _find_tool("SJCONVERTERPATH", *_SJCONVERTER)

_TOOLS = (
    ("ExifTool", "EXIFTOOLPATH", EXIFTOOLPATH, _EXIFTOOL_FOUND, "required",
     "https://exiftool.org (Debian / Ubuntu: sudo apt install libimage-exiftool-perl)"),
    ("RawTherapee", "RAWTHERAPEEPATH", RAWTHERAPEEPATH, _RAWTHERAPEE_FOUND, "required for DNG images",
     "https://rawtherapee.com/downloads (Debian / Ubuntu: sudo apt install rawtherapee)"),
    ("SJCam RAW converter", "SJCONVERTERPATH", SJCONVERTERPATH, _SJCONVERTER_FOUND, "required for SJCam .RAW images",
     "https://github.com/yanburman/sjcam_raw2dng/releases"),
)


def missing_tools():
    """List of (name, variable, path, need, install hint) for the tools not found."""
    return [(name, variable, path, need, hint)
            for name, variable, path, found, need, hint in _TOOLS if not found]


def missing_tools_message():
    """Human-readable description of the missing tools, '' when all are found."""
    lines = []
    for name, variable, path, need, hint in missing_tools():
        lines.append(f"- {name} ({need}): not found at {path}\n"
                     f"  Install it from {hint},\n"
                     f"  or set the environment variable {variable} to its path.")
    return "\n".join(lines)


def rawtherapee_environment(threads=None):
    """Environment of a RawTherapee conversion: ``threads`` threads (None: as
    many as physical cores, not logical ones) that sleep while they wait.

    By default RawTherapee (OpenMP) starts one thread per logical core and its
    idle threads spin: next to other busy processes (the alignment workers,
    several conversions at once) a conversion takes twice as long and twice
    the CPU time for the same image. The image written does not depend on the
    number of threads. A value already set by the user (OMP_NUM_THREADS,
    OMP_WAIT_POLICY) is kept."""
    environment = dict(os.environ)
    if threads is None:
        try:
            import psutil
            threads = psutil.cpu_count(logical=False)
        except Exception:
            threads = None
    if threads:
        environment.setdefault("OMP_NUM_THREADS", str(max(1, int(threads))))
    environment.setdefault("OMP_WAIT_POLICY", "PASSIVE")
    return environment


def require_tool(variable):
    """Return the path of an external tool (EXIFTOOLPATH, RAWTHERAPEEPATH or
    SJCONVERTERPATH); raise FileNotFoundError with install help if it is missing."""
    for name, tool_variable, path, need, hint in missing_tools():
        if tool_variable == variable:
            raise FileNotFoundError(
                f"{name} not found at {path}. Install it from {hint}, "
                f"or set the environment variable {variable} to its path.")
    return globals()[variable]


for _name, _variable, _path, _need, _hint in missing_tools():
    print(f"[WARNING] {_name} not found at {_path} ({_need}). Set {_variable} to its path.")
