"""Helper script for extracting Boosty credentials via browser console."""

from __future__ import annotations

import rich
from rich.syntax import Syntax

_JS_HELPER_SCRIPT = """\
(function() {
    let monitoring = true;

    // --- Extract auth token from the "auth" cookie ---
    // Boosty stores a JSON object in the "auth" cookie with an accessToken field.
    const getToken = () => {
        const raw = document.cookie.split("; ")
            .find(c => c.startsWith("auth="))
            ?.split("=").slice(1).join("=");  // .slice(1) handles '=' inside the value
        if (!raw) return null;
        try { return JSON.parse(decodeURIComponent(raw)).accessToken || null; }
        catch { return null; }
    };

    // --- Build the floating credentials box ---
    // Creates the box with buttons only once. Returns existing box on subsequent calls,
    // so buttons are never destroyed and stay clickable.
    const createBox = () => {
        const existing = document.getElementById("boosty-creds-box");
        if (existing) return existing;

        const box = document.createElement("div");
        box.id = "boosty-creds-box";
        box.style.cssText = `
            position:fixed; top:20px; right:20px; width:420px; max-height:80vh;
            background:#fff; border:1px solid #ccc; border-radius:8px;
            z-index:99999; font:14px sans-serif; color:#333;
            box-shadow:0 4px 12px rgba(0,0,0,.25); overflow-y:auto;
        `;

        // --- Toolbar with copy/close buttons ---
        const btnStyle = "padding:4px 8px; font-size:12px; cursor:pointer";
        const makeBtn = (label, onClick) => {
            const b = document.createElement("button");
            b.textContent = label;
            b.style.cssText = btnStyle;
            b.onclick = onClick;
            return b;
        };

        const toolbar = document.createElement("div");
        toolbar.style.cssText = "display:flex; gap:5px; padding:8px; border-bottom:1px solid #ccc; background:#f7f7f7";
        toolbar.append(
            makeBtn("Copy Token", () =>
                navigator.clipboard.writeText(document.getElementById("cred-token")?.textContent || "")),
            makeBtn("Copy Cookie", () =>
                navigator.clipboard.writeText(document.getElementById("cred-cookie")?.textContent || "")),
            makeBtn("Close and Stop Monitoring", () => { monitoring = false; box.remove(); }),
        );

        const content = document.createElement("div");
        content.id = "boosty-creds-content";
        content.style.padding = "12px";

        box.append(toolbar, content);
        document.body.appendChild(box);
        return box;
    };

    // --- Fill credentials into the box ---
    // Only the content area is updated, buttons in toolbar are untouched.
    const showCredentials = (token, cookies) => {
        createBox();
        const codeStyle = "display:block; background:#f5f5f5; padding:8px; border-radius:4px; white-space:pre-wrap; word-break:break-all;";
        document.getElementById("boosty-creds-content").innerHTML = `
            <h4 style="margin:6px 0">Access Token</h4>
            <code id="cred-token" style="${codeStyle}">Bearer ${token}</code>
            <h4 style="margin:12px 0 6px">Cookies</h4>
            <code id="cred-cookie" style="${codeStyle}">${cookies}</code>
        `;
    };

    // --- Hook into fetch() and XMLHttpRequest ---
    // On every network request, check if credentials are available and show them.
    const check = () => {
        if (!monitoring) return;
        const token = getToken();
        if (token) showCredentials(token, document.cookie);
    };

    const origFetch = window.fetch;
    window.fetch = async (...args) => { check(); return origFetch.apply(this, args); };

    const origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(...args) { check(); return origOpen.apply(this, args); };

    console.log("Boosty credential monitor started. Scroll the page to trigger detection.");
})();
"""


def _try_copy_to_clipboard(text: str) -> bool:
    """Try to copy text to clipboard. Return True on success."""
    try:
        import pyperclip  # noqa: PLC0415

        pyperclip.copy(text)
    except Exception:  # noqa: BLE001
        return False
    else:
        return True


def show_js_helper_script() -> None:
    """Show the JS helper script and try to copy it to clipboard."""
    rich.print(
        Syntax(
            _JS_HELPER_SCRIPT,
            'javascript',
            theme='dracula',
            word_wrap=False,
            background_color='#000000',
            tab_size=2,
        )
    )

    copied = _try_copy_to_clipboard(_JS_HELPER_SCRIPT)

    rich.print()
    if copied:
        rich.print(
            '[bold green]The script has been copied to your clipboard.[/bold green]'
        )
    else:
        rich.print(
            '[bold yellow]Could not copy to clipboard. Please copy the script manually.[/bold yellow]'
        )

    rich.print()
    rich.print('1. Open [link=https://boosty.to]boosty.to[/link] and log in.')
    rich.print('2. Paste the script into the browser console (F12).')
    rich.print('3. Scroll the page to trigger a network request.')
    rich.print('4. A floating box with your credentials will appear.')
    rich.print(
        '5. Click [bold]Close and Stop Monitoring[/bold] or refresh the page when done.'
    )
