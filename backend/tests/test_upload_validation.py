"""Tests for multipart submission validation across text, image, and pdf."""

import io


def test_valid_text_submission(client):
    response = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": "This is a valid compliant brand statement.",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["content_type"] == "text"
    assert data["role"] == "creator"
    assert data["status"] == "draft"
    assert data["version"] == 1
    assert data["text"] == "This is a valid compliant brand statement."
    assert "id" in data


def test_non_creator_role_rejected(client):
    for role in ["manager", "authorised_reviewer", "admin", "viewer"]:
        response = client.post(
            "/submissions",
            data={
                "content_type": "text",
                "role": role,
                "text": "Attempted by wrong role.",
            },
        )
        assert response.status_code == 403
        data = response.json()
        assert data["error"]["code"] == "forbidden"
        assert "Only creators" in data["error"]["message"]


def test_invalid_content_type(client):
    response = client.post(
        "/submissions",
        data={
            "content_type": "audio",
            "role": "creator",
            "text": "Audio content",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable_entity"


def test_empty_or_whitespace_text_rejected(client):
    # Empty string
    res1 = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": ""},
    )
    assert res1.status_code == 422
    assert "empty" in res1.json()["error"]["message"]

    # Whitespace only
    res2 = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": "   \n\t  "},
    )
    assert res2.status_code == 422
    assert "empty" in res2.json()["error"]["message"]


def test_text_length_limit(client):
    # Exactly 50,000 chars -> should succeed
    text_50k = "a" * 50000
    res_ok = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": text_50k},
    )
    assert res_ok.status_code == 201

    # 50,001 chars -> should fail
    text_50001 = "a" * 50001
    res_fail = client.post(
        "/submissions",
        data={"content_type": "text", "role": "creator", "text": text_50001},
    )
    assert res_fail.status_code == 422
    assert "50000" in res_fail.json()["error"]["message"]


def test_reject_text_with_file(client):
    response = client.post(
        "/submissions",
        data={
            "content_type": "text",
            "role": "creator",
            "text": "Text with file attached",
        },
        files={"file": ("notes.txt", io.BytesIO(b"some file bytes"), "text/plain")},
    )
    assert response.status_code == 422
    assert "File upload not allowed" in response.json()["error"]["message"]


def test_image_submission_success(client):
    # PNG
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    res_png = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("hero.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert res_png.status_code == 201
    assert res_png.json()["file_name"] == "hero.png"

    # JPEG
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    res_jpeg = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("hero.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
    )
    assert res_jpeg.status_code == 201

    # WEBP
    webp_bytes = b"RIFF\x14\x00\x00\x00WEBPVP8 " + b"\x00" * 50
    res_webp = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("hero.webp", io.BytesIO(webp_bytes), "image/webp")},
    )
    assert res_webp.status_code == 201


def test_image_rejected_with_text(client):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    response = client.post(
        "/submissions",
        data={
            "content_type": "image",
            "role": "creator",
            "text": "Extra disallowed text",
        },
        files={"file": ("hero.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert response.status_code == 422
    assert "Text content not allowed" in response.json()["error"]["message"]


def test_image_missing_file(client):
    response = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
    )
    assert response.status_code == 422
    assert "File is required" in response.json()["error"]["message"]


def test_image_invalid_magic_bytes(client):
    bad_bytes = b"NOT_AN_IMAGE_HEADER" + b"\x00" * 50
    response = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("fake.png", io.BytesIO(bad_bytes), "image/png")},
    )
    assert response.status_code == 422
    assert "Invalid image format" in response.json()["error"]["message"]


def test_image_size_limit_exceeded(client):
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1)
    response = client.post(
        "/submissions",
        data={"content_type": "image", "role": "creator"},
        files={"file": ("huge.png", io.BytesIO(oversized), "image/png")},
    )
    assert response.status_code == 422
    assert "5MB" in response.json()["error"]["message"]


def test_pdf_submission_success(client):
    pdf_bytes = b"%PDF-1.7\n%some content"
    response = client.post(
        "/submissions",
        data={"content_type": "pdf", "role": "creator"},
        files={"file": ("document.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert response.status_code == 201
    assert response.json()["file_name"] == "document.pdf"
    assert response.json()["content_type"] == "pdf"


def test_pdf_rejected_with_text(client):
    pdf_bytes = b"%PDF-1.4\n%content"
    response = client.post(
        "/submissions",
        data={
            "content_type": "pdf",
            "role": "creator",
            "text": "Some text",
        },
        files={"file": ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert response.status_code == 422
    assert "Text content not allowed" in response.json()["error"]["message"]


def test_pdf_missing_file(client):
    response = client.post(
        "/submissions",
        data={"content_type": "pdf", "role": "creator"},
    )
    assert response.status_code == 422
    assert "File is required" in response.json()["error"]["message"]


def test_pdf_invalid_magic_bytes(client):
    bad_pdf = b"NOT_A_PDF_HEADER"
    response = client.post(
        "/submissions",
        data={"content_type": "pdf", "role": "creator"},
        files={"file": ("corrupt.pdf", io.BytesIO(bad_pdf), "application/pdf")},
    )
    assert response.status_code == 422
    assert "%PDF-" in response.json()["error"]["message"]


def test_pdf_size_limit_exceeded(client):
    oversized_pdf = b"%PDF-1.7\n" + b"\x00" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/submissions",
        data={"content_type": "pdf", "role": "creator"},
        files={"file": ("huge.pdf", io.BytesIO(oversized_pdf), "application/pdf")},
    )
    assert response.status_code == 422
    assert "10MB" in response.json()["error"]["message"]

