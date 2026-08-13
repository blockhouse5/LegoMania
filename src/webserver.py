import asyncio
import os
import sys
import io
import machine
import updater
import version
import json
import gc


MAX_BODY_SIZE = 32768

running_tasks = {}

PROTECTED_FILES = (
    "boot.py",
    "webserver.py",
    "webrepl_cfg.py",
    "main.py",
    "config.py",
    "updater.py",
    "version.py",
    "lego.py", 
    "index.html"
)

# --------------------------------------------------
# Program output
# --------------------------------------------------

OUTPUT_MAX_CHARS = 12000

output_log = ""

# Keep the real print function for our development
# console before we inject custom print functions
# into user programs.
system_print = print


def append_output(program, text):

    global output_log

    prefix = "[" + program + "] "

    # Prefix each line so we can tell which
    # independently-running program produced it.
    lines = text.splitlines(True)

    if not lines:
        lines = [text]

    for line in lines:
        output_log += prefix + line

    # Prevent an endlessly-running castle from
    # eventually consuming all available RAM.
    if len(output_log) > OUTPUT_MAX_CHARS:
        output_log = output_log[-OUTPUT_MAX_CHARS:]


def clear_output():

    global output_log

    output_log = ""

def make_program_rows():

    rows = ""

    for name in get_python_files():

        # Hide protected system files
        if name in PROTECTED_FILES:
            continue

        running = is_running(name)

        if running:
            state = "● Running"
        else:
            state = "○ Stopped"

        # Open is always available
        buttons = (
            '<button '
            'type="button" '
            'onclick="openProgram(\'%s\')">'
            'Open'
            '</button>'
            % name
        )

        if running:

            buttons += (
                '<button '
                'type="button" '
                'onclick="stopProgram(\'%s\')">'
                'Stop'
                '</button>'
                % name
            )

        else:

            buttons += (
                '<button '
                'type="button" '
                'onclick="runProgram(\'%s\')">'
                'Run'
                '</button>'
                % name
            )

            buttons += (
                '<button '
                'type="button" '
                'onclick="deleteProgram(\'%s\')">'
                'Delete'
                '</button>'
                % name
            )

        rows += """
        <tr>
            <td>%s</td>
            <td>%s</td>
            <td>%s</td>
        </tr>
        """ % (
            html_escape(name),
            state,
            buttons
        )

    return rows


def make_program_print(program):

    def program_print(*args, **kwargs):

        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")

        text = sep.join(
            str(arg) for arg in args
        ) + end

        append_output(
            program,
            text
        )

        # Still show it on USB/mpremote while
        # we're developing.
        system_print(
            *args,
            **kwargs
        )

    return program_print

# --------------------------------------------------
# Helpers
# --------------------------------------------------

def html_escape(text):
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def url_decode(text):
    text = text.replace("+", " ")

    result = bytearray()
    i = 0

    while i < len(text):

        if text[i] == "%" and i + 2 < len(text):
            try:
                result.append(
                    int(text[i + 1:i + 3], 16)
                )
                i += 3
                continue
            except ValueError:
                pass

        for b in text[i].encode("utf-8"):
            result.append(b)

        i += 1

    return result.decode("utf-8")


def parse_form(body):
    values = {}

    if not body:
        return values

    for part in body.split("&"):

        if "=" in part:
            key, value = part.split("=", 1)

            values[url_decode(key)] = url_decode(value)

    return values


# --------------------------------------------------
# File handling
# --------------------------------------------------

def get_python_files():
    files = []

    for name in os.listdir():
        if name.endswith(".py"):
            files.append(name)

    files.sort()

    return files


def load_file(filename):
    with open(filename, "r") as f:
        return f.read()


def save_file(filename, code):
    with open(filename, "w") as f:
        f.write(code)


# --------------------------------------------------
# Task management
# --------------------------------------------------

def is_running(filename):
    return filename in running_tasks

async def run_program_task(
    filename,
    module
):

    try:

        await module.main()

        append_output(
            filename,
            "Program finished.\n"
        )


    except asyncio.CancelledError:

        append_output(
            filename,
            "Program stopped.\n"
        )

        raise


    except Exception as e:

        # Capture the complete MicroPython traceback
        trace = io.StringIO()

        sys.print_exception(
            e,
            trace
        )

        append_output(
            filename,
            "ERROR:\n"
            + trace.getvalue()
        )

        # Also show full exception on development
        # console.
        system_print(
            "Program error:",
            filename
        )

        sys.print_exception(e)


    finally:

        # If program ends or crashes, it should
        # no longer appear as Running.
        if filename in running_tasks:
            del running_tasks[filename]

async def start_program(filename):

    if is_running(filename):
        return filename + " is already running."

    module_name = filename

    if module_name.endswith(".py"):
        module_name = module_name[:-3]

    try:

        # Remove cached module so a newly edited
        # version gets loaded.
        if module_name in sys.modules:
            del sys.modules[module_name]

        module = __import__(module_name)

        # Give this user program its own print()
        # implementation.
        module.print = make_program_print(
            filename
        )

        if not hasattr(module, "main"):
            return (
                filename
                + " must contain async def main()"
            )

        task = asyncio.create_task(
            run_program_task(
                filename,
                module
            )
        )

        running_tasks[filename] = task

        print("Started:", filename)

        return "Started " + filename

    except Exception as e:

        return (
            "Could not start "
            + filename
            + ": "
            + str(e)
        )


async def stop_program(filename):

    if not is_running(filename):
        return filename + " is not running."

    task = running_tasks[filename]

    task.cancel()

    try:
        await task

    except asyncio.CancelledError:
        pass

    except Exception as e:
        print(
            "Error stopping",
            filename,
            ":",
            e
        )

    if filename in running_tasks:
        del running_tasks[filename]

    print("Stopped:", filename)

    return "Stopped " + filename

# --------------------------------------------------
# HTTP
# --------------------------------------------------

async def read_request(reader):

    request_line = await reader.readline()

    if not request_line:
        return "", ""

    request_line = request_line.decode(
        "utf-8",
        "replace"
    ).strip()

    content_length = 0

    while True:

        line = await reader.readline()

        if not line:
            break

        if line == b"\r\n":
            break

        text = line.decode(
            "utf-8",
            "replace"
        ).strip()

        if text.lower().startswith(
            "content-length:"
        ):

            content_length = int(
                text.split(":", 1)[1].strip()
            )


    if content_length > MAX_BODY_SIZE:
        raise Exception(
            "POST body exceeds maximum size"
        )


    body = ""

    if content_length:

        data = await reader.readexactly(
            content_length
        )

        body = data.decode(
            "utf-8",
            "replace"
        )


    return request_line, body

async def send_file(
    writer,
    filename,
    content_type
):

    headers = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: "
        + content_type
        + "\r\n"
        "Cache-Control: no-cache\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

    writer.write(
        headers.encode()
    )

    await writer.drain()

    with open(filename, "rb") as f:

        while True:

            chunk = f.read(1024)

            if not chunk:
                break

            writer.write(chunk)

            await writer.drain()


async def handle_client(reader, writer):

    filename = ""
    code = ""
    status = ""
    active_tab = "programs"
    update_info = None

    try:

        request_line, body = await read_request(
            reader
        )

        # --------------------------------------
        # STATIC HOME PAGE
        # --------------------------------------

        if request_line.startswith(
            "GET / "
        ):

            await send_file(
                writer,
                "index.html",
                "text/html; charset=utf-8"
            )

            return

        # --------------------------------------
        # VERSION API
        # --------------------------------------

        if request_line.startswith(
            "GET /api/version "
        ):

            response_body = json.dumps({
                "ok": True,
                "version": version.VERSION
            })

            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
            )

            writer.write(headers.encode())
            await writer.drain()

            writer.write(
                response_body.encode()
            )

            await writer.drain()

            return


        # --------------------------------------
        # CLEAR OUTPUT API
        # --------------------------------------

        if request_line.startswith(
            "POST /api/clear-output "
        ):

            clear_output()

            response_body = json.dumps({
                "ok": True,
                "message": "Output cleared."
            })

            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
            )

            writer.write(headers.encode())
            await writer.drain()

            writer.write(
                response_body.encode()
            )

            await writer.drain()

            return

        # --------------------------------------
        # INSTALL UPDATE API
        # --------------------------------------

        if request_line.startswith(
            "POST /api/install-update "
        ):

            print()
            print("Installing update...")

            result = updater.install_update()

            gc.collect()

            response_body = json.dumps(
                result
            )

            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
            )

            writer.write(
                headers.encode("utf-8")
            )

            await writer.drain()

            writer.write(
                response_body.encode("utf-8")
            )

            await writer.drain()

            if result.get("ok"):

                print()
                print(
                    "Update complete. "
                    "Restarting in 2 seconds..."
                )

                await asyncio.sleep(2)

                machine.reset()

            return


        # --------------------------------------
        # OUTPUT API
        # --------------------------------------

        if request_line.startswith(
            "GET /output "
        ):

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/plain; "
                "charset=utf-8\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
                + output_log
            )

            writer.write(
                response.encode("utf-8")
            )

            await writer.drain()

            return

        # --------------------------------------
        # PING API
        # --------------------------------------

        if request_line.startswith(
            "GET /ping"
        ):

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/plain\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
                "OK"
            )

            writer.write(
                response.encode("utf-8")
            )

            await writer.drain()

            return

        # --------------------------------------
        # UPDATE CHECK API
        # --------------------------------------

        if request_line.startswith(
            "GET /check-update "
        ):

            result = (
                updater.check_for_update()
            )

            body = json.dumps(
                result
            )

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json; "
                "charset=utf-8\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
                + body
            )

            writer.write(
                response.encode("utf-8")
            )

            await writer.drain()

            return

        # --------------------------------------
        # OPEN PROGRAM API
        # --------------------------------------

        if request_line.startswith(
            "POST /api/open "
        ):

            form = parse_form(body)

            filename = form.get(
                "filename",
                ""
            )

            try:

                code = load_file(
                    filename
                )

                response_body = json.dumps({
                    "ok": True,
                    "filename": filename,
                    "code": code
                })

            except Exception as e:

                response_body = json.dumps({
                    "ok": False,
                    "message": "Open failed: " + str(e)
                })

            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
            )

            writer.write(
                headers.encode("utf-8")
            )

            await writer.drain()

            writer.write(
                response_body.encode("utf-8")
            )

            await writer.drain()

            return

        # --------------------------------------
        # SAVE PROGRAM API
        # --------------------------------------

        if request_line.startswith(
            "POST /api/save "
        ):

            form = parse_form(body)

            filename = form.get(
                "filename",
                ""
            ).strip()

            code = form.get(
                "code",
                ""
            )

            if not filename:

                response_body = json.dumps({
                    "ok": False,
                    "message": "Please enter a filename."
                })

            else:

                if not filename.endswith(".py"):
                    filename += ".py"

                if is_running(filename):

                    response_body = json.dumps({
                        "ok": False,
                        "message":
                            filename
                            + " is running. "
                            + "Stop it before saving changes."
                    })

                else:

                    try:

                        save_file(
                            filename,
                            code
                        )

                        print(
                            "Saved:",
                            filename
                        )

                        response_body = json.dumps({
                            "ok": True,
                            "filename": filename,
                            "message":
                                "Saved "
                                + filename
                                + " successfully."
                        })

                    except Exception as e:

                        response_body = json.dumps({
                            "ok": False,
                            "message":
                                "Save failed: "
                                + str(e)
                        })


            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
            )

            writer.write(
                headers.encode("utf-8")
            )

            await writer.drain()

            writer.write(
                response_body.encode("utf-8")
            )

            await writer.drain()

            return

        # --------------------------------------
        # SAVE & RESTART API
        # --------------------------------------

        if request_line.startswith(
            "POST /api/save-restart "
        ):

            form = parse_form(body)

            filename = form.get(
                "filename",
                ""
            ).strip()

            code = form.get(
                "code",
                ""
            )

            if not filename:

                response_body = json.dumps({
                    "ok": False,
                    "message": "Please enter a filename."
                })

            else:

                if not filename.endswith(".py"):
                    filename += ".py"

                try:

                    if is_running(filename):
                        await stop_program(
                            filename
                        )

                    save_file(
                        filename,
                        code
                    )

                    result = await start_program(
                        filename
                    )

                    if result.startswith("Started"):

                        message = (
                            "Saved and restarted "
                            + filename
                            + " successfully."
                        )

                        ok = True

                    else:

                        message = result
                        ok = False

                    response_body = json.dumps({
                        "ok": ok,
                        "filename": filename,
                        "message": message
                    })

                except Exception as e:

                    response_body = json.dumps({
                        "ok": False,
                        "message":
                            "Save & Restart failed: "
                            + str(e)
                    })

            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
            )

            writer.write(
                headers.encode("utf-8")
            )

            await writer.drain()

            writer.write(
                response_body.encode("utf-8")
            )

            await writer.drain()

            return

        # --------------------------------------
        # RUN PROGRAM API
        # --------------------------------------

        if request_line.startswith(
            "POST /api/run "
        ):

            form = parse_form(body)

            filename = form.get(
                "filename",
                ""
            )

            result = await start_program(
                filename
            )

            response_body = json.dumps({
                "ok": result.startswith(
                    "Started"
                ),
                "message": result
            })

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
                + response_body
            )

            writer.write(
                response.encode("utf-8")
            )

            await writer.drain()

            return


        # --------------------------------------
        # STOP PROGRAM API
        # --------------------------------------

        if request_line.startswith(
            "POST /api/stop "
        ):

            form = parse_form(body)

            filename = form.get(
                "filename",
                ""
            )

            result = await stop_program(
                filename
            )

            response_body = json.dumps({
                "ok": True,
                "message": result
            })

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
                + response_body
            )

            writer.write(
                response.encode("utf-8")
            )

            await writer.drain()

            return

        # --------------------------------------
        # DELETE PROGRAM API
        # --------------------------------------

        if request_line.startswith(
            "POST /api/delete "
        ):

            form = parse_form(body)

            filename = form.get(
                "filename",
                ""
            )

            try:

                if filename in PROTECTED_FILES:

                    response_body = json.dumps({
                        "ok": False,
                        "message":
                            filename
                            + " is a protected system file."
                    })

                elif is_running(filename):

                    response_body = json.dumps({
                        "ok": False,
                        "message":
                            filename
                            + " is running. "
                            + "Stop it before deleting."
                    })

                else:

                    os.remove(filename)

                    module_name = filename

                    if module_name.endswith(".py"):
                        module_name = module_name[:-3]

                    if module_name in sys.modules:
                        del sys.modules[module_name]

                    print(
                        "Deleted:",
                        filename
                    )

                    response_body = json.dumps({
                        "ok": True,
                        "message":
                            "Deleted "
                            + filename
                            + " successfully."
                    })

            except Exception as e:

                response_body = json.dumps({
                    "ok": False,
                    "message":
                        "Delete failed: "
                        + str(e)
                })


            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
            )

            writer.write(
                headers.encode("utf-8")
            )

            await writer.drain()

            writer.write(
                response_body.encode("utf-8")
            )

            await writer.drain()

            return
        
        # --------------------------------------
        # PROGRAM LIST API
        # --------------------------------------

        if request_line.startswith(
            "GET /api/programs "
        ):

            response_body = make_program_rows()

            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "Cache-Control: no-cache\r\n"
                "Connection: close\r\n"
                "\r\n"
            )

            writer.write(
                headers.encode("utf-8")
            )

            await writer.drain()

            writer.write(
                response_body.encode("utf-8")
            )

            await writer.drain()

            return

        # --------------------------------------
        # NOT FOUND
        # --------------------------------------

        response = (
            "HTTP/1.1 404 Not Found\r\n"
            "Content-Type: text/plain\r\n"
            "Connection: close\r\n"
            "\r\n"
            "Not Found"
        )

        writer.write(
            response.encode("utf-8")
        )

        await writer.drain()


    except Exception as e:

        print("HTTP error:")
            
        sys.print_exception(e)


    finally:

        try:
            writer.close()
            await writer.wait_closed()

        except:
            pass


# --------------------------------------------------
# Main server
# --------------------------------------------------

async def main():

    print()
    print("ESP32 LEGO IDE")
    print("--------------")

    server = await asyncio.start_server(
        handle_client,
        "0.0.0.0",
        80
    )

    print(
        "Web server listening on port 80"
    )

    while True:
        await asyncio.sleep(3600)


asyncio.run(main())