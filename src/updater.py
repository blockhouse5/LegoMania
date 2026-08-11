import json
import requests
import version
import os


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


# --------------------------------------------------
# Download Manifest
# --------------------------------------------------

def download_update():

    response = None

    try:

        print("Reading update manifest...")

        response = requests.get(
            MANIFEST_URL
        )

        if response.status_code != 200:
            return {
                "ok": False,
                "message":
                    "Manifest HTTP {}".format(
                        response.status_code
                    )
            }

        manifest = json.loads(
            response.text
        )

        files = manifest.get(
            "files",
            []
        )

        if not files:
            return {
                "ok": False,
                "message":
                    "Manifest contains no files"
            }

        results = []

        for file_info in files:

            result = download_file(
                file_info
            )

            results.append(result)

            if not result.get("ok"):

                return {
                    "ok": False,
                    "message":
                        "Download failed",
                    "files": results
                }

        return {
            "ok": True,
            "version":
                manifest.get("version"),
            "files": results,
            "message":
                "Update files downloaded"
        }

    except Exception as e:

        return {
            "ok": False,
            "message":
                "Update download failed: "
                + str(e)
        }

    finally:

        if response:
            try:
                response.close()
            except:
                pass            

# --------------------------------------------------
# Download Files
# --------------------------------------------------

def download_file(file_info):

    name = file_info.get("name")
    url = file_info.get("url")

    if not name or not url:
        raise Exception(
            "Update file is missing name or URL"
        )

    new_name = name + ".new"

    response = None

    try:

        print("Downloading:", name)
        print("From:", url)

        response = requests.get(url)

        if response.status_code != 200:
            raise Exception(
                "HTTP {}".format(
                    response.status_code
                )
            )

        data = response.content

        if not data:
            raise Exception(
                "Downloaded file is empty"
            )

        with open(new_name, "wb") as f:
            f.write(data)

        print(
            "Saved:",
            new_name,
            "(",
            len(data),
            "bytes )"
        )

        return {
            "ok": True,
            "name": name,
            "new_name": new_name,
            "size": len(data)
        }

    except Exception as e:

        # A partial .new file must not survive
        # a failed download.
        try:
            os.remove(new_name)
        except:
            pass

        return {
            "ok": False,
            "name": name,
            "message": str(e)
        }

    finally:

        if response:
            try:
                response.close()
            except:
                pass  

# --------------------------------------------------
# Helper function for Install Files
# -------------------------------------------------- 

def file_exists(name):
    try:
        os.stat(name)
        return True
    except OSError:
        return False 

# --------------------------------------------------
# Install Files
# -------------------------------------------------- 

def install_file(name, simulate_failure=False):

    live_name = name
    new_name = name + ".new"
    bak_name = name + ".bak"

    # Make sure the downloaded file exists
    try:
        os.stat(new_name)
    except:
        return {
            "ok": False,
            "name": name,
            "message": new_name + " does not exist"
        }

    # Remove an old backup if one exists
    try:
        os.remove(bak_name)
    except:
        pass

    try:

        # Preserve the current live file
        if file_exists(live_name):

            os.rename(
                live_name,
                bak_name
            )

            print(
                "Backed up:",
                live_name,
                "->",
                bak_name
            )

        # Test hook: deliberately fail after the
        # live file has been moved to .bak.
        if simulate_failure:
            raise Exception(
                "Simulated install failure"
            )


        # Promote the downloaded file
        os.rename(
            new_name,
            live_name
        )

        print(
            "Installed:",
            new_name,
            "->",
            live_name
        )

        return {
            "ok": True,
            "name": name,
            "backup": bak_name
        }

    except Exception as e:

        print(
            "Install failed:",
            name,
            e
        )

        # Try to restore the old file
        try:

            os.stat(bak_name)

            # Remove a partially-installed live file,
            # if one somehow exists
            try:
                os.remove(live_name)
            except:
                pass

            os.rename(
                bak_name,
                live_name
            )

            print(
                "Rollback restored:",
                live_name
            )

        except Exception as rollback_error:

            print(
                "Rollback failed:",
                rollback_error
            )

        return {
            "ok": False,
            "name": name,
            "message": str(e)
        }     

# --------------------------------------------------
# Rollback Files if Failure
# --------------------------------------------------   

def rollback_file(name):

    live_name = name
    bak_name = name + ".bak"

    if not file_exists(bak_name):
        print(
            "No backup available for:",
            name
        )

        return {
            "ok": False,
            "name": name,
            "message": "No backup available"
        }

    try:

        if file_exists(live_name):
            os.remove(live_name)

        os.rename(
            bak_name,
            live_name
        )

        print(
            "Rolled back:",
            name
        )

        return {
            "ok": True,
            "name": name
        }

    except Exception as e:

        print(
            "Rollback failed:",
            name,
            e
        )

        return {
            "ok": False,
            "name": name,
            "message": str(e)
        }

def install_update():

    response = None
    installed_files = []

    try:

        print("Starting update installation...")

        # --------------------------------------
        # Read manifest
        # --------------------------------------

        response = requests.get(
            MANIFEST_URL
        )

        if response.status_code != 200:

            return {
                "ok": False,
                "message":
                    "Manifest HTTP {}".format(
                        response.status_code
                    )
            }

        manifest = json.loads(
            response.text
        )

        files = manifest.get(
            "files",
            []
        )

        target_version = manifest.get(
            "version"
        )

        if not files:

            return {
                "ok": False,
                "message":
                    "Manifest contains no files"
            }

        # Close manifest response before
        # downloading update files.
        response.close()
        response = None


        # --------------------------------------
        # Download ALL files first
        # --------------------------------------

        print()
        print("Downloading update files...")

        for file_info in files:

            result = download_file(
                file_info
            )

            if not result.get("ok"):

                return {
                    "ok": False,
                    "message":
                        "Download failed for "
                        + result.get(
                            "name",
                            "unknown file"
                        )
                }


        # --------------------------------------
        # Verify ALL .new files exist
        # --------------------------------------

        print()
        print("Verifying downloaded files...")

        for file_info in files:

            name = file_info.get("name")

            new_name = name + ".new"

            if not file_exists(new_name):

                return {
                    "ok": False,
                    "message":
                        "Missing staged file: "
                        + new_name
                }

            print(
                "Verified:",
                new_name
            )


        # --------------------------------------
        # Install files
        # --------------------------------------

        print()
        print("Installing update files...")

        for file_info in files:

            name = file_info.get("name")

            result = install_file(
                name
            )

            if not result.get("ok"):

                print()
                print(
                    "Install failed.",
                    "Rolling back update..."
                )

                # Roll back anything already
                # installed during this transaction.
                for installed_name in reversed(
                    installed_files
                ):

                    rollback_file(
                        installed_name
                    )

                return {
                    "ok": False,
                    "message":
                        "Install failed for "
                        + name
                        + ". Update rolled back."
                }

            installed_files.append(
                name
            )


        # --------------------------------------
        # Success
        # --------------------------------------

        print()
        print(
            "Update installed successfully."
        )

        return {
            "ok": True,
            "version": target_version,
            "files": installed_files,
            "message":
                "Update installed successfully"
        }


    except Exception as e:

        print()
        print(
            "Unexpected update error:",
            e
        )

        # Best effort rollback of anything
        # already installed.
        for installed_name in reversed(
            installed_files
        ):

            rollback_file(
                installed_name
            )

        return {
            "ok": False,
            "message":
                "Update failed: "
                + str(e)
        }


    finally:

        if response:
            try:
                response.close()
            except:
                pass