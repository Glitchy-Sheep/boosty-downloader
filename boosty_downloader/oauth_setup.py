#!/usr/bin/env python3
"""OAuth setup utility for configuring OAuth tokens"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from boosty_downloader.src.boosty_api.models.oauth import OAuthTokens
from boosty_downloader.src.boosty_api.utils.oauth_manager import OAuthManager

# Constants
TOKEN_PARTS_COUNT = 4  # access_token, refresh_token, expires_at, device_id
DEFAULT_TOKEN_EXPIRY_HOURS = 1
SECONDS_PER_HOUR = 3600

console = Console()
app = typer.Typer(add_completion=False)


def _show_auto_extract_script() -> None:
    """Show JavaScript code for automatic OAuth token extraction"""
    console.print('[bold cyan]JavaScript Code for Automatic Token Extraction[/bold cyan]')
    console.print()
    console.print('[yellow]Follow these steps:[/yellow]')
    console.print('1. Open [bold]boosty.to[/bold] in your browser and login')
    console.print('2. Open Developer Tools ([bold]F12[/bold] or Ctrl+Shift+I)')
    console.print('3. Go to [bold]Console[/bold] tab')
    console.print('4. Copy and paste the following JavaScript code:')
    console.print()

    js_code = """
// Boosty OAuth Token Extractor
(function() {
    console.log('🔍 Extracting OAuth tokens from Boosty cookies...');

    const result = {
        access_token: null,
        refresh_token: null,
        expires_at: null,
        device_id: null
    };

    // Extract data from cookies
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');

        if (name === '_clientId') {
            result.device_id = value;
        }

        if (name === 'auth') {
            try {
                // Decode URL-encoded JSON
                const decodedAuth = decodeURIComponent(value);
                const authData = JSON.parse(decodedAuth);

                result.access_token = authData.accessToken;
                result.refresh_token = authData.refreshToken;

                // Convert milliseconds to seconds
                if (authData.expiresAt) {
                    result.expires_at = Math.floor(authData.expiresAt / 1000);
                }
            } catch (e) {
                console.warn('Failed to parse auth cookie:', e);
            }
        }
    }

    // Check if we have minimum required data
    if (!result.device_id) {
        console.error('❌ _clientId not found in cookies');
        console.log('💡 Make sure you are logged in to boosty.to');
        return;
    }

    if (!result.access_token) {
        console.error('❌ accessToken not found in auth cookie');
        console.log('💡 Make sure you are logged in to boosty.to');
        return;
    }

    // Set default expiration if not found
    if (!result.expires_at) {
        result.expires_at = Math.floor(Date.now() / 1000) + 3600; // 1 hour from now
        console.warn('⚠️ expires_at not found, setting to 1 hour from now');
    }

    // Set refresh_token to access_token if not found
    if (!result.refresh_token) {
        result.refresh_token = result.access_token;
        console.warn('⚠️ refresh_token not found, using access_token as placeholder');
    }

    console.log('✅ OAuth tokens extracted successfully!');
    console.log('📋 Copy the following TOKEN STRING and paste it into the terminal:');
    console.log('');

    // Create a single line with pipe-separated values for easier parsing
    const tokenString = `${result.access_token}|${result.refresh_token}|${result.expires_at}|${result.device_id}`;

    console.log('=== COPY THIS TOKEN STRING (START) ===');
    console.log(tokenString);
    console.log('=== COPY THIS TOKEN STRING (END) ===');
    console.log('');

    // Also copy to clipboard if available
    if (navigator.clipboard) {
        navigator.clipboard.writeText(tokenString)
            .then(() => console.log('📋 Token string copied to clipboard!'))
            .catch(() => console.log('⚠️ Could not copy to clipboard, please copy manually'));
    }

    console.log('⚠️ IMPORTANT: Copy ONLY the token string between the === markers above');
    console.log('✨ Format: access_token|refresh_token|expires_at|device_id');

    return result;
})();
"""

    console.print(js_code, style='green', highlight=False, markup=False)
    console.print()
    console.print('5. Press Enter to execute the code', style='yellow')
    console.print('6. Copy the TOKEN STRING that appears (one line with | separators)', style='yellow')
    console.print('7. Return to this terminal and paste the token string when prompted', style='yellow')
    console.print()
    console.print('[red]Note:[/red] If the script shows errors, try:')
    console.print('- Refreshing the page')
    console.print('- Navigating to any author page on boosty.to')
    console.print('- Making sure you are logged in')
    console.print()


@app.command()
def setup_oauth(
    tokens_file: str = typer.Option(
        'oauth_tokens.json',
        '--tokens-file',
        '-f',
        help='Path to OAuth tokens file',
    ),
    auto_extract: bool = typer.Option(
        False,
        '--auto-extract',
        '-a',
        help='Show JavaScript code for automatic token extraction',
    ),
) -> None:
    """Setup OAuth tokens for automatic authentication"""
    console.print('[bold green]OAuth Setup for Boosty Downloader[/bold green]')
    console.print()

    if auto_extract:
        _show_auto_extract_script()
        return

    console.print('[yellow]You can extract OAuth data in two ways:[/yellow]')
    console.print('1. [bold]Automatic[/bold]: Run JavaScript code in browser console')
    console.print('2. [bold]Manual[/bold]: Extract data manually from DevTools')
    console.print()

    choice = Prompt.ask(
        'Choose extraction method',
        choices=['auto', 'manual'],
        default='auto',
    )

    tokens = None

    if choice == 'auto':
        _show_auto_extract_script()
        console.print()

        token_data = Prompt.ask('Paste the token string from browser console')
        try:
            import json

            # Clean the data
            token_data = token_data.strip()

            # Check if it's a pipe-separated string (new format)
            if '|' in token_data and not token_data.startswith('{'):
                console.print('[cyan]📝 Detected new token string format[/cyan]')
                parts = token_data.split('|')

                if len(parts) != TOKEN_PARTS_COUNT:
                    console.print(f'[red]Invalid token string format. Expected {TOKEN_PARTS_COUNT} parts, got {len(parts)}[/red]')
                    console.print('[yellow]Falling back to manual input...[/yellow]')
                    choice = 'manual'
                    tokens = None
                else:
                    access_token, refresh_token, expires_at_str, device_id = parts

                    try:
                        expires_at = int(expires_at_str)
                    except ValueError:
                        console.print('[red]Invalid expires_at in token string[/red]')
                        choice = 'manual'
                        tokens = None
                    else:
                        console.print('[green]✅ Token string parsed successfully![/green]')
                        tokens = OAuthTokens(
                            access_token=access_token,
                            refresh_token=refresh_token,
                            expires_at=expires_at,
                            device_id=device_id,
                        )
            else:
                # Try to parse as JSON (legacy format)
                console.print('[cyan]📝 Attempting JSON parsing (legacy format)[/cyan]')

                # Remove any extra quotes that might have been copied
                if token_data.startswith('"') and token_data.endswith('"'):
                    token_data = token_data[1:-1]

                # Handle escaped quotes
                token_data = token_data.replace('\\"', '"')

                data = json.loads(token_data)

                # Validate required fields
                required_fields = ['access_token', 'refresh_token', 'expires_at', 'device_id']
                missing_fields = [field for field in required_fields if field not in data]

                if missing_fields:
                    console.print(f'[red]Missing required fields: {missing_fields}[/red]')
                    console.print('[yellow]Falling back to manual input...[/yellow]')
                    choice = 'manual'
                    tokens = None
                else:
                    tokens = OAuthTokens(
                        access_token=data['access_token'],
                        refresh_token=data['refresh_token'],
                        expires_at=data['expires_at'],
                        device_id=data['device_id'],
                    )
                    console.print('[green]✅ JSON parsed successfully![/green]')

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            console.print(f'[red]Error parsing data: {e}[/red]')
            console.print('[yellow]Falling back to manual input...[/yellow]')
            choice = 'manual'
            tokens = None

    if choice == 'manual' or tokens is None:
        if choice == 'manual' or tokens is None:
            console.print('[yellow]Manual extraction - You need to extract the following data:[/yellow]')
            console.print('1. Access Token (from Authorization header)')
            console.print('2. Refresh Token (from browser storage or previous auth)')
            console.print('3. Device ID (from browser cookies)')
            console.print('4. Token expiration time (Unix timestamp)')
            console.print()

            console.print('[cyan]Instructions:[/cyan]')
            console.print('1. Open browser DevTools (F12)')
            console.print('2. Go to boosty.to and login')
            console.print('3. Find a API request in Network tab')
            console.print('4. Copy Authorization header (starts with "Bearer ")')
            console.print('5. Find Device ID in Application->Cookies')
            console.print()
        # Get tokens from user
        access_token = Prompt.ask('Enter Access Token (without "Bearer " prefix)')
        refresh_token = Prompt.ask('Enter Refresh Token')
        device_id = Prompt.ask('Enter Device ID')

        # Ask for expiration time or use default
        expires_at_str = Prompt.ask(
            'Enter token expiration (Unix timestamp, press Enter for 1 hour from now)',
            default='',
        )

        if not expires_at_str:
            expires_at = int(datetime.now(timezone.utc).timestamp()) + (DEFAULT_TOKEN_EXPIRY_HOURS * SECONDS_PER_HOUR)  # 1 hour from now
        else:
            try:
                expires_at = int(expires_at_str)
            except ValueError:
                console.print(f'[red]Invalid expiration time, using {DEFAULT_TOKEN_EXPIRY_HOURS} hour from now[/red]')
                expires_at = int(datetime.now(timezone.utc).timestamp()) + (DEFAULT_TOKEN_EXPIRY_HOURS * SECONDS_PER_HOUR)

        # Create OAuth tokens
        try:
            tokens = OAuthTokens(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                device_id=device_id,
            )
        except Exception as e:
            console.print(f'[red]Error creating OAuth tokens: {e}[/red]')
            sys.exit(1)

    if tokens is None:
        console.print('[red]Failed to create OAuth tokens[/red]')
        sys.exit(1)

    # Save tokens using OAuth manager
    oauth_manager = OAuthManager(Path(tokens_file))
    oauth_manager.set_tokens(tokens)

    console.print()
    console.print(f'[green]✅ OAuth tokens saved to {tokens_file}[/green]')
    console.print('[yellow]You can now use boosty-downloader with automatic token refresh![/yellow]')

    # Show token info
    console.print()
    console.print('[cyan]Token information:[/cyan]')
    console.print(f'Access Token: {tokens.access_token[:20]}...')
    console.print(f'Refresh Token: {tokens.refresh_token[:20]}...')
    console.print(f'Device ID: {tokens.device_id}')
    console.print(f'Expires At: {datetime.fromtimestamp(tokens.expires_at, timezone.utc)} ({tokens.expires_at})')


@app.command()
def extract_script() -> None:
    """Show JavaScript code for automatic OAuth token extraction"""
    _show_auto_extract_script()


@app.command()
def check_tokens(
    tokens_file: str = typer.Option(
        'oauth_tokens.json',
        '--tokens-file',
        '-f',
        help='Path to OAuth tokens file',
    ),
) -> None:
    """Check status of OAuth tokens"""
    console.print('[bold blue]OAuth Token Status[/bold blue]')
    console.print()

    oauth_manager = OAuthManager(Path(tokens_file))

    if not oauth_manager.has_tokens():
        console.print(f'[red]❌ No OAuth tokens found in {tokens_file}[/red]')
        console.print('[yellow]Run "python -m boosty_downloader.oauth_setup setup-oauth" to configure[/yellow]')
        return

    tokens = oauth_manager._tokens
    if tokens is None:
        console.print('[red]❌ Failed to load tokens[/red]')
        return

    console.print(f'[green]✅ OAuth tokens found in {tokens_file}[/green]')
    console.print()
    console.print(f'Access Token: {tokens.access_token[:20]}...')
    console.print(f'Refresh Token: {tokens.refresh_token[:20]}...')
    console.print(f'Device ID: {tokens.device_id}')
    console.print(f'Expires At: {datetime.fromtimestamp(tokens.expires_at, timezone.utc)}')

    if tokens.is_expired():
        console.print('[yellow]⚠️  Access token is expired (will be refreshed automatically)[/yellow]')
    else:
        console.print('[green]✅ Access token is still valid[/green]')


if __name__ == '__main__':
    app()
