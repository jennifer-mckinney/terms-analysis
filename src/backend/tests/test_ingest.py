from app.services.ingest import extract_text_from_bytes


def test_extracts_html_text():
    html = b"<html><body><h1>Title</h1><p>Policy text here.</p></body></html>"
    text = extract_text_from_bytes("policy.html", "text/html", html)
    assert "Title" in text
    assert "Policy text here." in text


def test_extracts_rtf_text():
    rtf = b"{\\rtf1\\ansi This is \\b bold\\b0 text.}"
    text = extract_text_from_bytes("policy.rtf", "application/rtf", rtf)
    assert "This is" in text
    assert "bold" in text
    assert "text." in text
