import json
import requests
import version


# --------------------------------------------------
# GitHub update configuration
# --------------------------------------------------

MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "blockhouse5/"
    "LegoMania/"
    "main/"
    "updates/manifest.json"
)


# --------------------------------------------------
# Version comparison
# --------------------------------------------------

def version_tuple(value):
    parts = value.split(".")

    result = []

    for part in parts:
        try:
            result.append(int(part))
        except:
            result.append(0)

    return tuple(result)


def is_newer_version(latest, current):
    return version_tuple(latest) > version_tuple(current)


# --------------------------------------------------
# Check GitHub
# --------------------------------------------------

def check_for_update():

    current_version = version.VERSION

    response = None

    try:

        print("Checking GitHub for updates...")
        print("Current version:", current_version)

        response = requests.get(
            MANIFEST_URL
        )

        if response.status_code != 200:

            return {
                "ok": False,
                "current": current_version,
                "latest": None,
                "available": False,
                "message":
                    "GitHub returned HTTP {}".format(
                        response.status_code
                    )
            }

        manifest = json.loads(
            response.text
        )

        latest_version = manifest.get(
            "version"
        )

        if not latest_version:

            return {
                "ok": False,
                "current": current_version,
                "latest": None,
                "available": False,
                "message":
                    "Manifest has no version"
            }

        available = is_newer_version(
            latest_version,
            current_version
        )

        if available:
            message = (
                "Version {} is available".format(
                    latest_version
                )
            )
        else:
            message = (
                "LEGO Project Lab is up to date"
            )

        return {
            "ok": True,
            "current": current_version,
            "latest": latest_version,
            "available": available,
            "message": message,
            "notes": manifest.get(
                "notes",
                ""
            )
        }

    except Exception as e:

        return {
            "ok": False,
            "current": current_version,
            "latest": None,
            "available": False,
            "message":
                "Update check failed: {}".format(e)
        }

    finally:

        if response:
            try:
                response.close()
            except:
                pass