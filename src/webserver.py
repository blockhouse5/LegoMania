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
    "lego.py"
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
# HTML
# --------------------------------------------------

def make_page(
    filename="",
    code="",
    status="",
    active_tab="programs",
    update_info=None
):

    rows = ""

    for name in get_python_files():

        # Hide system files from normal Programs view
        if name in PROTECTED_FILES:
            continue

        if is_running(name):
            state = "● Running"
        else:
            state = "○ Stopped"

        buttons = (
            '<button name="action" '
            'value="open:%s">Open</button>'
            % name
        )

        if is_running(name):

            buttons += (
                '<button name="action" '
                'value="stop:%s">Stop</button>'
                % name
            )

        else:

            buttons += (
                '<button name="action" '
                'value="run:%s">Run</button>'
                % name
            )

            buttons += (
                '<button '
                'name="action" '
                'value="delete:%s" '
                'onclick="return confirm('
                "'Are you sure you want to delete %s?'"
                ');">'
                'Delete'
                '</button>'
                % (name, name)
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

    update_html = ""

    if update_info:

        if (
            update_info.get("ok")
            and update_info.get("installed")
        ):

            update_html = """
            <div   
                id="update-restart"
                class="update-result update-current">

                <strong>
                Update installed successfully!
                </strong>

                <p>
                Version %s has been installed.
                </p>

                <p>
                LEGO Project Lab is restarting...
                </p>

                <p 
                id="reconnect-status"
                class="small-note">
                Waiting for restart...
                </p>

            </div>
            """ % html_escape(
                update_info.get(
                    "version",
                    ""
                )
            )

        elif update_info.get("ok"):

            if update_info.get("available"):

                update_html = """
                <div class="update-result update-available">

                    <strong>Update available!</strong>

                    <p>
                    Installed version: %s<br>
                    Available version: %s
                    </p>

                    <p>%s</p>

                    <form method="POST">

                    <button
                        type="submit"
                        name="action"
                        value="install_update"
                        onclick="return confirm(
                            'Install this update and restart LEGO Project Lab?'
                        );"
                    >
                        Install Update
                    </button>

                    </form>

                </div>
                """ % (
                    html_escape(
                        update_info.get(
                            "current",
                            ""
                        )
                    ),
                    html_escape(
                        update_info.get(
                            "latest",
                            ""
                        )
                    ),
                    html_escape(
                        update_info.get(
                            "notes",
                            ""
                        )
                    )
                )

            else:

                update_html = """
                <div class="update-result update-current">

                    <strong>
                    LEGO Project Lab is up to date.
                    </strong>

                    <p>
                    Installed version: %s
                    </p>

                </div>
                """ % html_escape(
                    update_info.get(
                        "current",
                        ""
                    )
                )

        else:

            update_html = """
            <div class="update-result update-error">

                <strong>
                Update check failed.
                </strong>

                <p>%s</p>

            </div>
            """ % html_escape(
                update_info.get(
                    "message",
                    ""
                )
            )

    page = """<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<div class="header">

<h1>LEGO Project Lab</h1>

<div>
    Build it. Program it. Make it move.
</div>

</div>

<style>

:root {
    --lego-red: #d91e18;
    --lego-yellow: #ffd500;
    --lego-blue: #0055bf;
    --lego-green: #237841;

    --page-bg: #f2f3f5;
    --panel-bg: #ffffff;
    --text: #222222;
    --border: #d3d3d3;
}

body {
    font-family: Arial, sans-serif;
    margin: 0;
    background: var(--page-bg);
    color: var(--text);
}


/* --------------------------------------------------
   Header
   -------------------------------------------------- */

.header {
    padding: 18px 20px;
    background: var(--lego-red);
    color: white;
    border-bottom: 6px solid var(--lego-yellow);
}

.header h1 {
    margin: 0;
    font-size: 28px;
    letter-spacing: 0.5px;
}


/* --------------------------------------------------
   Tabs
   -------------------------------------------------- */

.tabs {
    display: flex;
    background: var(--lego-blue);
}

.tab-button {
    padding: 14px 24px;
    border: none;
    background: var(--lego-blue);
    color: white;
    font-size: 18px;
    cursor: pointer;
    margin: 0;
}

.tab-button.active {
    background: var(--lego-yellow);
    color: #111;
    font-weight: bold;
}

.tab-button:hover {
    opacity: 0.9;
}


/* --------------------------------------------------
   Tab contents
   -------------------------------------------------- */

.tab-content {
    display: none;
    padding: 20px;
}

.tab-content.active {
    display: block;
}


/* --------------------------------------------------
   Programs table
   -------------------------------------------------- */

table {
    width: 100%%;
    border-collapse: collapse;
    background: var(--panel-bg);
    border-radius: 8px;
    overflow: hidden;
}

th {
    background: #e7e7e7;
    font-weight: bold;
}

td,
th {
    border-bottom: 1px solid var(--border);
    padding: 12px;
    text-align: left;
}


/* --------------------------------------------------
   Buttons
   -------------------------------------------------- */

button {
    font-size: 16px;
    padding: 9px 15px;
    margin-right: 6px;
    margin-top: 5px;

    border: none;
    border-radius: 6px;

    background: var(--lego-blue);
    color: white;

    cursor: pointer;
}

button:hover {
    opacity: 0.85;
}


/* New program button */

.new-button {
    background: var(--lego-green);
    margin-bottom: 15px;
}


/* --------------------------------------------------
   Editor
   -------------------------------------------------- */

.editor-box {
    max-width: 950px;
    background: var(--panel-bg);
    padding: 20px;
    border-radius: 8px;
}

input {
    width: 100%%;
    font-size: 18px;
    padding: 9px;
    box-sizing: border-box;

    border: 2px solid var(--lego-blue);
    border-radius: 5px;
}

textarea {
    width: 100%%;
    height: 400px;

    font-family:
        Consolas,
        Monaco,
        monospace;

    font-size: 16px;

    padding: 12px;
    box-sizing: border-box;

    border: 2px solid var(--lego-blue);
    border-radius: 5px;

    background: #fcfcfc;
}


/* --------------------------------------------------
   Status
   -------------------------------------------------- */

.status {
    margin-top: 20px;
    padding: 12px;

    background: #fff6bf;

    border-left: 6px solid var(--lego-yellow);

    white-space: pre-wrap;

    border-radius: 5px;
}


/* --------------------------------------------------
   Output console
   -------------------------------------------------- */

.output-console {
    background: #181818;
    color: #eeeeee;

    font-family:
        Consolas,
        Monaco,
        monospace;

    font-size: 15px;
    line-height: 1.5;

    padding: 15px;

    min-height: 350px;
    max-height: 600px;

    overflow-y: auto;
    white-space: pre-wrap;

    border: 3px solid var(--lego-blue);
    border-top: 6px solid var(--lego-red);
    border-radius: 8px;

    box-sizing: border-box;
}

/* Output tab heading */

#output h2 {
    margin-top: 0;
}


/* Clear Output button */

#output button {
    background: var(--lego-red);
    color: white;
}


/* Give the whole Output area a clean panel */

#output {
    background: var(--page-bg);
}


/* --------------------------------------------------
   Settings
   -------------------------------------------------- */

.settings-box {
    max-width: 650px;
    background: var(--panel-bg);
    padding: 20px;
    border-radius: 8px;
}

.settings-box h2 {
    margin-top: 0;
}

.version-display {
    font-size: 18px;
    margin-bottom: 20px;
}

.update-result {
    margin-top: 20px;
    padding: 15px;
    border-radius: 6px;
}

.update-current {
    background: #e8f5e9;
    border-left: 6px solid var(--lego-green);
}

.update-available {
    background: #fff6bf;
    border-left: 6px solid var(--lego-yellow);
}

.update-error {
    background: #fde8e8;
    border-left: 6px solid var(--lego-red);
}

.small-note {
    font-size: 14px;
    color: #555555;
}

</style>

<script>

function refreshOutput() {

    var request = new XMLHttpRequest();

    request.open(
        "GET",
        "/output",
        true
    );

    request.onreadystatechange = function() {

        if (
            request.readyState === 4 &&
            request.status === 200
        ) {

            var output =
                document.getElementById(
                    "output-log"
                );

            output.textContent =
                request.responseText;

            output.scrollTop =
                output.scrollHeight;
        }
    };

    request.send();
}

function showTab(name) {

    var tabs =
        document.getElementsByClassName(
            "tab-content"
        );

    var buttons =
        document.getElementsByClassName(
            "tab-button"
        );

    for (var i = 0; i < tabs.length; i++) {
        tabs[i].classList.remove("active");
    }

    for (var i = 0; i < buttons.length; i++) {
        buttons[i].classList.remove("active");
    }

    document
        .getElementById(name)
        .classList
        .add("active");

    document
        .getElementById(name + "-button")
        .classList
        .add("active");

    if (name == "output") {
        refreshOutput();
    }
}

function setupEditor() {

    var editor =
        document.getElementById("code");

    editor.addEventListener(
        "keydown",
        function(event) {

            if (event.key === "Tab") {

                event.preventDefault();

                var start =
                    editor.selectionStart;

                var end =
                    editor.selectionEnd;

                var value =
                    editor.value;

                var spaces = "    ";

                editor.value =
                    value.substring(0, start)
                    + spaces
                    + value.substring(end);

                editor.selectionStart =
                    start + spaces.length;

                editor.selectionEnd =
                    start + spaces.length;
            }
        }
    );
}

function escapeHtml(text) {

    var div =
        document.createElement("div");

    div.textContent =
        text == null ? "" : String(text);

    return div.innerHTML;
}

function checkForUpdates() {

    var button =
        document.getElementById(
            "check-update-button"
        );

    var status =
        document.getElementById(
            "update-status"
        );

    button.disabled = true;
    button.textContent = "Checking...";

    status.innerHTML =
        "<p>Checking GitHub for updates...</p>";

    var request = new XMLHttpRequest();

    request.open(
        "GET",
        "/check-update",
        true
    );

    request.timeout = 20000;

    request.onreadystatechange = function() {

        if (request.readyState !== 4) {
            return;
        }

        button.disabled = false;
        button.textContent =
            "Check for Updates";

        if (request.status === 200) {

            try {

                var result =
                    JSON.parse(
                        request.responseText
                    );

                if (!result.ok) {

                    status.innerHTML =
                        '<div class="update-result update-error">'
                        + '<strong>Update check failed.</strong>'
                        + '<p>'
                        + escapeHtml(
                            result.message || ""
                        )
                        + '</p>'
                        + '</div>';

                }
                else if (result.available) {

                    status.innerHTML =
                        '<div class="update-result update-available">'
                        + '<strong>Update available!</strong>'
                        + '<p>'
                        + 'Installed version: '
                        + escapeHtml(result.current)
                        + '<br>'
                        + 'Available version: '
                        + escapeHtml(result.latest)
                        + '</p>'
                        + '<p>'
                        + escapeHtml(result.notes || "")
                        + '</p>'
                        + '<form method="POST">'
                        + '<button '
                        + 'type="submit" '
                        + 'name="action" '
                        + 'value="install_update">'
                        + 'Install Update'
                        + '</button>'
                        + '</form>'
                        + '</div>';

                }
                else {

                    status.innerHTML =
                        '<div class="update-result update-current">'
                        + '<strong>'
                        + 'LEGO Project Lab is up to date.'
                        + '</strong>'
                        + '<p>'
                        + 'Installed version: '
                        + escapeHtml(result.current)
                        + '</p>'
                        + '</div>';
                }

            }
            catch (e) {

                status.innerHTML =
                    '<div class="update-result update-error">'
                    + '<strong>Invalid update response.</strong>'
                    + '</div>';
            }

        }
        else {

            status.innerHTML =
                '<div class="update-result update-error">'
                + '<strong>Could not contact LEGO Project Lab.</strong>'
                + '</div>';
        }
    };

    request.ontimeout = function() {

        button.disabled = false;
        button.textContent =
            "Check for Updates";

        status.innerHTML =
            '<div class="update-result update-error">'
            + '<strong>Update check timed out.</strong>'
            + '<p>Please try again.</p>'
            + '</div>';
    };

    request.send();
}

function reconnectAfterUpdate() {

    var status =
        document.getElementById(
            "reconnect-status"
        );

    var attempts = 0;
    var maxAttempts = 30;

    function tryReconnect() {

        attempts++;

        status.textContent =
            "Reconnecting to LEGO Project Lab...";

        var request =
            new XMLHttpRequest();

        request.open(
            "GET",
            "/ping?t=" + Date.now(),
            true
        );

        request.timeout = 3000;

        var finished = false;

        function retry() {

            if (finished) {
                return;
            }

            finished = true;

            if (attempts >= maxAttempts) {

                status.innerHTML =
                    "LEGO Project Lab is taking longer "
                    + "than expected to restart.<br>"
                    + "You can refresh this page and try again.";

                return;
            }

            setTimeout(
                tryReconnect,
                2000
            );
        }

        request.onload = function() {

            if (finished) {
                return;
            }

            if (request.status === 200) {

                finished = true;

                status.textContent =
                    "Connected! Reloading...";

                setTimeout(
                    function() {
                        window.location.replace("/");
                    },
                    500
                );

            }
            else {
                retry();
            }
        };

        request.onerror = function() {
            retry();
        };

        request.ontimeout = function() {
            retry();
        };

        try {
            request.send();
        }
        catch (e) {
            retry();
        }
    }

    status.textContent =
        "Waiting for LEGO Project Lab to restart...";

    setTimeout(
        tryReconnect,
        4000
    );
}

/* Automatic refresh */
setInterval(refreshOutput, 1000);


function newProgram() {

    document.getElementById(
        "filename"
    ).value = "";

    document.getElementById(
        "code"
    ).value =
`import asyncio

async def main():

    while True:

        # Your LEGO code goes here

        await asyncio.sleep(1)
`;

    showTab("editor");

    document.getElementById(
        "filename"
    ).focus();
}

</script>

</head>


<body>


<div class="tabs">

<button
    id="programs-button"
    class="tab-button"
    onclick="showTab('programs')"
>
    Programs
</button>


<button
    id="editor-button"
    class="tab-button"
    onclick="showTab('editor')"
>
    Editor
</button>

<button
    id="output-button"
    class="tab-button"
    onclick="showTab('output')"
>
    Output
</button>

<button
    id="settings-button"
    class="tab-button"
    onclick="showTab('settings')"
>
    Settings
</button>

</div>


<!-- ========================================== -->
<!-- PROGRAMS TAB                               -->
<!-- ========================================== -->

<div
    id="programs"
    class="tab-content"
>

<button
    type="button"
    class="new-button"
    onclick="newProgram()"
>
    + New Program
</button>


<form method="POST">

<table>

<tr>
    <th>Program</th>
    <th>Status</th>
    <th>Actions</th>
</tr>

%s

</table>

</form>

</div>


<!-- ========================================== -->
<!-- EDITOR TAB                                 -->
<!-- ========================================== -->

<div
    id="editor"
    class="tab-content"
>

<div class="editor-box">

<form method="POST">

<label>
    <strong>Filename</strong>
</label>

<br>

<input
    id="filename"
    type="text"
    name="filename"
    value="%s"
    placeholder="my_program.py"
>

<br><br>


<label>
    <strong>Python code</strong>
</label>

<br>

<textarea
    id="code"
    name="code"
    spellcheck="false"
    autocorrect="off"
    autocapitalize="off"
>%s</textarea>

<br>


<button
    type="submit"
    name="action"
    value="save"
>
    Save
</button>


<button
    type="submit"
    name="action"
    value="save_restart"
>
    Save & Restart
</button>

</form>


<div class="status">

<strong>Status</strong>

<br>

%s

</div>

</div>

</div>

<!-- ========================================== -->
<!-- OUTPUT TAB                                 -->
<!-- ========================================== -->

<div
    id="output"
    class="tab-content"
>

<h2>Program Output</h2>

<form method="POST">

<button
    type="submit"
    name="action"
    value="clear_output"
>
    Clear Output
</button>

</form>

<br>

<div
    id="output-log"
    class="output-console"
></div>

</div>

<!-- ========================================== -->
<!-- SETTINGS TAB                               -->
<!-- ========================================== -->

<div
    id="settings"
    class="tab-content"
>

<div class="settings-box">

<h2>LEGO Project Lab Settings</h2>

<div class="version-display">

<strong>Installed Version</strong>

<br>

%s

</div>

<button
    type="button"
    id="check-update-button"
    onclick="checkForUpdates()"
>
    Check for Updates
</button>

<div
    id="update-status"
></div>

%s

</div>

</div>

<script>

showTab("%s");

setupEditor();

if (
    document.getElementById(
        "update-restart"
    )
) {
    reconnectAfterUpdate();
}

</script>


</body>

</html>
""" % (
        rows,
        html_escape(filename),
        html_escape(code),
        html_escape(status),
        html_escape(version.VERSION),
        update_html,
        active_tab
    )

    return page


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


async def handle_client(reader, writer):

    filename = ""
    code = ""
    status = ""
    active_tab = "programs"
    update_info = None
    reboot_after_response = False

    try:

        request_line, body = await read_request(
            reader
        )

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

            if reboot_after_response:

                print()
                print(
                    "Update complete."
                    " Restarting in 2 seconds..."
                )

                await asyncio.sleep(2)

                machine.reset()

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

        if request_line.startswith("POST"):

            form = parse_form(body)

            action = form.get(
                "action",
                ""
            )


            # --------------------------------------
            # OPEN
            # --------------------------------------

            if action.startswith("open:"):

                filename = action[5:]

                try:

                    code = load_file(filename)

                    status = (
                        "Opened "
                        + filename
                    )

                    active_tab = "editor"

                except Exception as e:

                    status = (
                        "Open failed: "
                        + str(e)
                    )


            # --------------------------------------
            # RUN
            # --------------------------------------

            elif action.startswith("run:"):

                filename = action[4:]

                status = await start_program(
                    filename
                )

                # Load selected program into editor
                try:
                    code = load_file(filename)
                except:
                    code = ""


            # --------------------------------------
            # STOP
            # --------------------------------------

            elif action.startswith("stop:"):

                filename = action[5:]

                status = await stop_program(
                    filename
                )

                try:
                    code = load_file(filename)
                except:
                    code = ""


            # --------------------------------------
            # DELETE
            # --------------------------------------

            elif action.startswith("delete:"):

                filename = action[7:]

                if filename in PROTECTED_FILES:

                    status = (
                        filename
                        + " is a protected system file."
                    )

                elif is_running(filename):

                    status = (
                        filename
                        + " is running. "
                        + "Stop it before deleting."
                    )

                else:

                    try:

                        os.remove(filename)

                        # Remove cached module too
                        module_name = filename

                        if module_name.endswith(".py"):
                            module_name = module_name[:-3]

                        if module_name in sys.modules:
                            del sys.modules[module_name]

                        status = (
                            "Deleted "
                            + filename
                            + " successfully."
                        )

                        print(
                            "Deleted:",
                            filename
                        )

                        # Clear editor because the file
                        # no longer exists
                        filename = ""
                        code = ""

                    except Exception as e:

                        status = (
                            "Delete failed: "
                            + str(e)
                        )

            # --------------------------------------
            # SAVE
            # --------------------------------------

            elif action == "save":

                filename = form.get(
                    "filename",
                    ""
                ).strip()

                code = form.get(
                    "code",
                    ""
                )


                if not filename:

                    status = (
                        "Please enter a filename."
                    )

                else:

                    if not filename.endswith(".py"):
                        filename += ".py"


                    if is_running(filename):

                        status = (
                            filename
                            + " is running. "
                            + "Stop it before saving changes."
                        )

                    else:

                        try:

                            save_file(
                                filename,
                                code
                            )

                            status = (
                                "Saved "
                                + filename
                                + " successfully."
                            )

                            active_tab = "editor"

                            print(
                                "Saved:",
                                filename
                            )

                        except Exception as e:

                            status = (
                                "Save failed: "
                                + str(e)
                            )

            # --------------------------------------
            # CLEAR OUTPUT
            # --------------------------------------

            elif action == "clear_output":

                clear_output()

                status = "Output cleared."

                active_tab = "output"


            # --------------------------------------
            # INSTALL UPDATE
            # --------------------------------------

            elif action == "install_update":

                active_tab = "settings"

                print()
                print("Installing update...")

                result = updater.install_update()

                gc.collect()

                if result.get("ok"):

                    new_version = result.get(
                        "version",
                        ""
                    )

                    update_info = {
                        "ok": True,
                        "installed": True,
                        "version": new_version,
                        "message":
                            "Update installed successfully. "
                            "LEGO Project Lab is restarting..."
                    }

                    status = (
                        "Update installed successfully."
                    )

                    reboot_after_response = True

                else:

                    update_info = {
                        "ok": False,
                        "message": result.get(
                            "message",
                            "Update installation failed."
                        )
                    }

                    status = update_info["message"]

            # --------------------------------------
            # SAVE & RESTART
            # --------------------------------------

            elif action == "save_restart":

                filename = form.get(
                    "filename",
                    ""
                ).strip()

                code = form.get(
                    "code",
                    ""
                )

                active_tab = "editor"


                if not filename:

                    status = (
                        "Please enter a filename."
                    )

                else:

                    if not filename.endswith(".py"):
                        filename += ".py"


                    try:

                        # Stop old version if running

                        if is_running(filename):

                            await stop_program(
                                filename
                            )


                        # Save new version

                        save_file(
                            filename,
                            code
                        )


                        # Start new version

                        status = await start_program(
                            filename
                        )


                        if status.startswith("Started"):

                            status = (
                                "Saved and restarted "
                                + filename
                                + " successfully."
                            )


                        print(
                            "Saved and restarted:",
                            filename
                        )


                    except Exception as e:

                        status = (
                            "Save & Restart failed: "
                            + str(e)
                        )


        page = make_page(
            filename,
            code,
            status,
            active_tab,
            update_info
        )


        headers = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Connection: close\r\n"
            "\r\n"
        )

        writer.write(
            headers.encode("utf-8")
        )

        await writer.drain()

        writer.write(
            page.encode("utf-8")
        )

        await writer.drain()

        if reboot_after_response:

            print()
            print(
                "Update complete. "
                "Restarting in 2 seconds..."
            )

            await asyncio.sleep(2)

            machine.reset()


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