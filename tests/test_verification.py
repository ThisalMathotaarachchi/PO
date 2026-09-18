"""Tests for completion verification."""

import pytest
from pathlib import Path
from app.agent.verification import verify_completion, _extract_file_references, _check_file_references


@pytest.mark.asyncio
async def test_verify_completion_no_files_required():
    """Task that doesn't require files passes."""
    result = await verify_completion(
        workspace_path="/tmp/test",
        task_prompt="Explain how Python decorators work",
        files_created=set(),
        files_modified=set()
    )
    assert result.passed


@pytest.mark.asyncio
async def test_verify_completion_file_task_no_files():
    """Task requiring files fails if no files created."""
    result = await verify_completion(
        workspace_path="/tmp/test",
        task_prompt="Create a website with HTML and CSS",
        files_created=set(),
        files_modified=set()
    )
    assert not result.passed
    assert "no files were created" in result.message.lower()


@pytest.mark.asyncio
async def test_verify_completion_html_missing_css(tmp_path):
    """HTML referencing missing CSS fails verification (Elyra scenario)."""
    # Create HTML file with CSS reference
    html_file = tmp_path / "index.html"
    html_file.write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="styles.css">
    </head>
    <body>
        <h1>Elyra Fashion</h1>
    </body>
    </html>
    """)
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a premium clothing website for Elyra",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert not result.passed
    assert "styles.css" in result.message
    assert "styles.css" in result.missing_files


@pytest.mark.asyncio
async def test_verify_completion_html_missing_js(tmp_path):
    """HTML referencing missing JS fails verification."""
    html_file = tmp_path / "index.html"
    html_file.write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="script.js"></script>
    </head>
    <body>
        <h1>Test</h1>
    </body>
    </html>
    """)
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert not result.passed
    assert "script.js" in result.message
    assert "script.js" in result.missing_files


@pytest.mark.asyncio
async def test_verify_completion_html_all_files_exist(tmp_path):
    """HTML with all referenced files passes verification."""
    html_file = tmp_path / "index.html"
    html_file.write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="styles.css">
        <script src="script.js"></script>
    </head>
    <body>
        <h1>Complete Site</h1>
    </body>
    </html>
    """)
    
    # Create referenced files
    (tmp_path / "styles.css").write_text("body { margin: 0; }")
    (tmp_path / "script.js").write_text("console.log('loaded');")
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html", "styles.css", "script.js"},
        files_modified=set()
    )
    
    assert result.passed


@pytest.mark.asyncio
async def test_verify_completion_html_subdirectory(tmp_path):
    """HTML in subdirectory with relative CSS reference."""
    subdir = tmp_path / "site"
    subdir.mkdir()
    
    html_file = subdir / "index.html"
    html_file.write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="css/styles.css">
    </head>
    </html>
    """)
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"site/index.html"},
        files_modified=set()
    )
    
    assert not result.passed
    assert "css/styles.css" in result.message or "styles.css" in result.message


@pytest.mark.asyncio
async def test_verify_completion_html_external_urls_ignored(tmp_path):
    """HTML with external URLs doesn't fail verification."""
    html_file = tmp_path / "index.html"
    html_file.write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="https://cdn.example.com/styles.css">
        <script src="https://code.jquery.com/jquery.min.js"></script>
    </head>
    <body>
        <img src="https://example.com/image.png">
    </body>
    </html>
    """)
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert result.passed


@pytest.mark.asyncio
async def test_extract_file_references_html():
    """Extract CSS and JS references from HTML."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="styles.css">
        <link rel="stylesheet" href="theme.css">
        <script src="app.js"></script>
    </head>
    <body>
        <img src="logo.png">
    </body>
    </html>
    """
    
    refs = _extract_file_references(html, '.html')
    assert "styles.css" in refs
    assert "theme.css" in refs
    assert "app.js" in refs
    assert "logo.png" in refs


def test_extract_file_references_css():
    """Extract @import and url() from CSS."""
    css = """
    @import "base.css";
    body {
        background: url(bg.png);
        font-face: url('fonts/main.woff');
    }
    """
    
    refs = _extract_file_references(css, '.css')
    assert "base.css" in refs
    assert "bg.png" in refs
    assert "fonts/main.woff" in refs


def test_extract_file_references_js():
    """Extract relative imports from JavaScript."""
    js = """
    import React from 'react';
    import './styles.css';
    import { utils } from './utils.js';
    const data = require('./data.json');
    """
    
    refs = _extract_file_references(js, '.js')
    # Should extract relative imports
    assert any('./styles.css' in ref or 'styles.css' in ref for ref in refs)
    assert any('./utils.js' in ref or 'utils.js' in ref for ref in refs)
    assert any('./data.json' in ref or 'data.json' in ref for ref in refs)


def test_check_file_references_mixed_status(tmp_path):
    """Some files exist, some don't."""
    html_file = tmp_path / "index.html"
    html_file.write_text("""
    <link rel="stylesheet" href="exists.css">
    <link rel="stylesheet" href="missing.css">
    <script src="exists.js"></script>
    <script src="missing.js"></script>
    """)
    
    # Create some of the referenced files (empty - should be flagged)
    (tmp_path / "exists.css").write_text("")
    (tmp_path / "exists.js").write_text("")
    
    problems, missing = _check_file_references(tmp_path, {"index.html"})
    
    assert "missing.css" in missing
    assert "missing.js" in missing
    # Empty files are also reported as problems
    assert "exists.css" in missing
    assert "exists.js" in missing
    # Also check problems contain the right messages
    assert any("missing.css" in p for p in problems)
    assert any("missing.js" in p for p in problems)
    assert any("exists.css" in p and "empty" in p for p in problems)
    assert any("exists.js" in p and "empty" in p for p in problems)


@pytest.mark.asyncio
async def test_verify_completion_elyra_full_scenario(tmp_path):
    """
    Full Elyra scenario: HTML references CSS and JS, both missing.
    Verification must fail and list both missing files.
    """
    html_file = tmp_path / "index.html"
    html_file.write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Elyra - Premium Fashion</title>
        <link rel="stylesheet" href="styles.css">
    </head>
    <body>
        <nav>Navigation</nav>
        <section class="hero">Hero Section</section>
        <section class="products">Product Showcase</section>
        <section class="story">Brand Story</section>
        <section class="newsletter">Newsletter</section>
        <footer>Footer</footer>
        <script src="script.js"></script>
    </body>
    </html>
    """)
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a premium clothing website for my fictional clothing brand Elyra. Make it a polished, responsive ecommerce landing page with a hero section, navigation, product showcase, product cards, brand story, newsletter section, and footer.",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert not result.passed, "Verification should fail when referenced files are missing"
    assert "styles.css" in result.missing_files, "Missing CSS should be detected"
    assert "script.js" in result.missing_files, "Missing JS should be detected"
    assert "styles.css" in result.message, "Error message should mention missing CSS"
    assert "script.js" in result.message, "Error message should mention missing JS"


@pytest.mark.asyncio
async def test_verify_completion_elyra_complete(tmp_path):
    """
    Elyra scenario after fix: all files exist.
    Verification should pass.
    """
    html_file = tmp_path / "index.html"
    html_file.write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Elyra</title>
        <link rel="stylesheet" href="styles.css">
    </head>
    <body>
        <h1>Elyra Fashion</h1>
        <script src="script.js"></script>
    </body>
    </html>
    """)
    
    (tmp_path / "styles.css").write_text("body { font-family: sans-serif; }")
    (tmp_path / "script.js").write_text("document.addEventListener('DOMContentLoaded', function() {});")
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a premium clothing website for Elyra",
        files_created={"index.html", "styles.css", "script.js"},
        files_modified=set()
    )
    
    assert result.passed, f"Verification should pass when all files exist. Message: {result.message}"
    assert len(result.missing_files) == 0, "No files should be missing"


@pytest.mark.asyncio
async def test_verify_completion_created_path_is_directory(tmp_path):
    """Verification fails when a created path is a directory instead of a file."""
    # Create a directory where a file was expected
    (tmp_path / "styles.css").mkdir()
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website with styles.css",
        files_created={"styles.css"},
        files_modified=set()
    )
    
    assert not result.passed
    assert "is a directory, not a file" in result.message
    assert "styles.css" in result.missing_files


@pytest.mark.asyncio
async def test_verify_completion_modified_path_is_directory(tmp_path):
    """Verification fails when a modified path is a directory instead of a file."""
    (tmp_path / "script.js").mkdir()
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Update script.js",
        files_created=set(),
        files_modified={"script.js"}
    )
    
    assert not result.passed
    assert "is a directory, not a file" in result.message
    assert "script.js" in result.missing_files


def test_validate_html_structure_valid(tmp_path):
    """Valid HTML with doctype, html, head, body passes."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test</title>
    </head>
    <body>
        <h1>Hello</h1>
    </body>
    </html>
    """
    (tmp_path / "index.html").write_text(html)
    
    from app.agent.verification import _validate_html_structure
    result = _validate_html_structure(html)
    assert result is None, f"Valid HTML should pass, got: {result}"


def test_validate_html_structure_missing_doctype(tmp_path):
    """HTML missing DOCTYPE fails."""
    html = """
    <html>
    <head>
        <title>Test</title>
    </head>
    <body>
        <h1>Hello</h1>
    </body>
    </html>
    """
    from app.agent.verification import _validate_html_structure
    result = _validate_html_structure(html)
    assert result is not None
    assert "DOCTYPE" in result


def test_validate_html_structure_missing_head(tmp_path):
    """HTML missing head fails."""
    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <h1>Hello</h1>
    </body>
    </html>
    """
    from app.agent.verification import _validate_html_structure
    result = _validate_html_structure(html)
    assert result is not None
    assert "head" in result.lower()


def test_validate_html_structure_missing_body(tmp_path):
    """HTML missing body fails."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test</title>
    </head>
    </html>
    """
    from app.agent.verification import _validate_html_structure
    result = _validate_html_structure(html)
    assert result is not None
    assert "body" in result.lower()


def test_validate_html_structure_missing_html(tmp_path):
    """HTML missing html tag fails."""
    html = """
    <!DOCTYPE html>
    <head>
        <title>Test</title>
    </head>
    <body>
        <h1>Hello</h1>
    </body>
    """
    from app.agent.verification import _validate_html_structure
    result = _validate_html_structure(html)
    assert result is not None
    assert "html" in result.lower()


@pytest.mark.asyncio
async def test_verify_completion_html_structure_validation(tmp_path):
    """Verification fails when HTML lacks basic document structure."""
    # HTML missing doctype and body
    (tmp_path / "index.html").write_text("""
    <html>
    <head>
        <title>Test</title>
    </head>
    </html>
    """)
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert not result.passed
    assert "DOCTYPE" in result.message or "body" in result.message


@pytest.mark.asyncio
async def test_verify_completion_valid_html_passes(tmp_path):
    """Valid HTML with proper structure passes verification."""
    (tmp_path / "index.html").write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Site</title>
    </head>
    <body>
        <h1>Welcome</h1>
    </body>
    </html>
    """)
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert result.passed, f"Valid HTML should pass: {result.message}"


# Runtime verification tests

@pytest.mark.asyncio
async def test_verify_static_site_runtime_skips_non_static(tmp_path):
    """Runtime verification is skipped for non-static sites."""
    from app.agent.verification import _verify_static_site_runtime
    
    (tmp_path / "main.py").write_text("print('hello')")
    
    passed, message, missing = await _verify_static_site_runtime(
        tmp_path, {"main.py"}, 5.0
    )
    
    assert passed
    assert "Not a static site" in message


@pytest.mark.asyncio
async def test_verify_static_site_runtime_no_html(tmp_path):
    """Runtime verification skipped when no HTML files."""
    from app.agent.verification import _verify_static_site_runtime
    
    (tmp_path / "style.css").write_text("body {}")
    
    passed, message, missing = await _verify_static_site_runtime(
        tmp_path, {"style.css"}, 5.0
    )
    
    assert passed
    assert "Not a static site" in message


@pytest.mark.asyncio
async def test_verify_static_site_runtime_success(tmp_path):
    """Runtime verification logic for a valid static site (mocked)."""
    from app.agent.verification import _verify_static_site_runtime
    from app.tools.processes import ProcessManager
    from app.tools.base import ToolContext
    from unittest.mock import AsyncMock, MagicMock
    
    (tmp_path / "index.html").write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test</title>
        <link rel="stylesheet" href="styles.css">
    </head>
    <body>
        <h1>Test</h1>
        <script src="script.js"></script>
    </body>
    </html>
    """)
    (tmp_path / "styles.css").write_text("body { margin: 0; }")
    (tmp_path / "script.js").write_text("console.log('loaded');")
    
    # Mock ProcessManager
    mock_process_manager = AsyncMock(spec=ProcessManager)
    mock_process_manager.start_process.return_value = MagicMock(status="success")
    mock_process_manager.stop_process.return_value = MagicMock(status="success")
    
    # We can't easily test the full flow without a real server, but we can verify
    # the function is called correctly by checking the static detection
    from app.agent.verification import _is_static_site
    assert _is_static_site(tmp_path, {"index.html", "styles.css", "script.js"}) is True
    
    # Test that the static site detection works
    passed, message, missing = await _verify_static_site_runtime(
        tmp_path, {"index.html", "styles.css", "script.js"}, 5.0,
        process_manager=mock_process_manager,
    )
    
    # The mock will be called but we don't await the actual server
    # This test mainly ensures the function doesn't crash on valid input


@pytest.mark.asyncio
async def test_verify_static_site_runtime_missing_asset(tmp_path):
    """Runtime verification logic when referenced asset is missing."""
    from app.agent.verification import _verify_static_site_runtime
    from app.tools.processes import ProcessManager
    from unittest.mock import AsyncMock, MagicMock
    
    (tmp_path / "index.html").write_text("""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="missing.css">
    </head>
    <body></body>
    </html>
    """)
    # missing.css does not exist
    
    mock_process_manager = AsyncMock(spec=ProcessManager)
    mock_process_manager.start_process.return_value = MagicMock(status="success")
    mock_process_manager.stop_process.return_value = MagicMock(status="success")
    
    # The function will try to start a server and check
    # Since missing.css doesn't exist, it won't be in assets_to_check
    # but the static verification should catch this
    from app.agent.verification import _is_static_site
    assert _is_static_site(tmp_path, {"index.html"}) is True


@pytest.mark.asyncio
async def test_verify_completion_with_runtime_verification_disabled(tmp_path):
    """verify_completion with verify_runtime=False should not run runtime verification."""
    (tmp_path / "index.html").write_text("""
    <!DOCTYPE html>
    <html>
    <head><title>Test</title></head>
    <body><h1>Test</h1></body>
    </html>
    """)
    
    result = await verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html"},
        files_modified=set(),
        verify_runtime=False,
    )
    
    assert result.passed
    assert result.message == "Task completion verified."


@pytest.mark.asyncio
async def test_verify_completion_runtime_verification_error_handling(tmp_path):
    """verify_completion handles runtime verification errors gracefully."""
    from unittest.mock import AsyncMock, MagicMock
    from app.tools.processes import ProcessManager
    from app.tools.base import ToolContext
    
    (tmp_path / "index.html").write_text("""
    <!DOCTYPE html>
    <html>
    <head><title>Test</title></head>
    <body><h1>Test</h1></body>
    </html>
    """)
    
    # Mock ProcessManager to simulate server startup failure
    mock_process_manager = AsyncMock(spec=ProcessManager)
    mock_process_manager.start_process.return_value = MagicMock(status="failure", error="Failed to start server")
    
    # We need to test the internal function directly with the mock
    from app.agent.verification import _verify_static_site_runtime
    
    passed, message, missing = await _verify_static_site_runtime(
        tmp_path, {"index.html"}, 0.1,
        process_manager=mock_process_manager,
    )
    
    assert not passed
    assert "Failed to start verification server" in message


def test_is_static_site_detection(tmp_path):
    """Test static site detection logic."""
    from app.agent.verification import _is_static_site
    
    # Static site with HTML
    assert _is_static_site(tmp_path, {"index.html"}) is True
    assert _is_static_site(tmp_path, {"page.htm"}) is True
    assert _is_static_site(tmp_path, {"index.html", "styles.css"}) is True
    
    # Not a static site
    assert _is_static_site(tmp_path, {"main.py"}) is False
    assert _is_static_site(tmp_path, {"style.css"}) is False
    assert _is_static_site(tmp_path, {"script.js"}) is False
    assert _is_static_site(tmp_path, set()) is False


def test_find_free_port():
    """Test that _find_free_port returns a valid port."""
    from app.agent.verification import _find_free_port
    
    port = _find_free_port()
    assert isinstance(port, int)
    assert 1024 <= port <= 65535
    
    # Should be able to bind to it
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
