"""Tests for completion verification."""

import pytest
from pathlib import Path
from app.agent.verification import verify_completion, _extract_file_references, _check_file_references


def test_verify_completion_no_files_required():
    """Task that doesn't require files passes."""
    result = verify_completion(
        workspace_path="/tmp/test",
        task_prompt="Explain how Python decorators work",
        files_created=set(),
        files_modified=set()
    )
    assert result.passed


def test_verify_completion_file_task_no_files():
    """Task requiring files fails if no files created."""
    result = verify_completion(
        workspace_path="/tmp/test",
        task_prompt="Create a website with HTML and CSS",
        files_created=set(),
        files_modified=set()
    )
    assert not result.passed
    assert "no files were created" in result.message.lower()


def test_verify_completion_html_missing_css(tmp_path):
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
    
    result = verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a premium clothing website for Elyra",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert not result.passed
    assert "styles.css" in result.message
    assert "styles.css" in result.missing_files


def test_verify_completion_html_missing_js(tmp_path):
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
    
    result = verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert not result.passed
    assert "script.js" in result.message
    assert "script.js" in result.missing_files


def test_verify_completion_html_all_files_exist(tmp_path):
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
    
    result = verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html", "styles.css", "script.js"},
        files_modified=set()
    )
    
    assert result.passed


def test_verify_completion_html_subdirectory(tmp_path):
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
    
    result = verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"site/index.html"},
        files_modified=set()
    )
    
    assert not result.passed
    assert "css/styles.css" in result.message or "styles.css" in result.message


def test_verify_completion_html_external_urls_ignored(tmp_path):
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
    
    result = verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a website",
        files_created={"index.html"},
        files_modified=set()
    )
    
    assert result.passed


def test_extract_file_references_html():
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
    
    # Create some of the referenced files
    (tmp_path / "exists.css").write_text("")
    (tmp_path / "exists.js").write_text("")
    
    missing = _check_file_references(tmp_path, {"index.html"})
    
    assert "missing.css" in missing
    assert "missing.js" in missing
    assert "exists.css" not in missing
    assert "exists.js" not in missing


def test_verify_completion_elyra_full_scenario(tmp_path):
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
    
    result = verify_completion(
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


def test_verify_completion_elyra_complete(tmp_path):
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
    
    result = verify_completion(
        workspace_path=str(tmp_path),
        task_prompt="Create a premium clothing website for Elyra",
        files_created={"index.html", "styles.css", "script.js"},
        files_modified=set()
    )
    
    assert result.passed, f"Verification should pass when all files exist. Message: {result.message}"
    assert len(result.missing_files) == 0, "No files should be missing"
