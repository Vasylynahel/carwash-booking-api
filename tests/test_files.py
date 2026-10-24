from pathlib import Path

from app.core.config import settings
from tests.helpers import make_car

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64


def upload(client, headers, name="photo.png", content=PNG, ctype="image/png", **data):
    return client.post(
        "/api/files/upload", headers=headers, files={"file": (name, content, ctype)}, data=data
    )


def test_upload_requires_auth(client):
    r = client.post("/api/files/upload", files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 401


def test_upload_download_replace_delete(client, make_client_user):
    u = make_client_user()
    r = upload(client, u["headers"])
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["mimetype"] == "image/png" and f["size"] == len(PNG)

    content = client.get(f"/api/files/{f['id']}/content", headers=u["headers"])
    assert content.status_code == 200 and content.content == PNG

    rep = client.put(
        f"/api/files/{f['id']}", headers=u["headers"], files={"file": ("doc.pdf", PDF, "application/pdf")}
    )
    assert rep.status_code == 200 and rep.json()["mimetype"] == "application/pdf"
    assert client.get(f"/api/files/{f['id']}/content", headers=u["headers"]).content == PDF
    assert len(list(Path(settings.upload_dir).iterdir())) == 1  # старий файл прибрано з диска

    assert client.delete(f"/api/files/{f['id']}", headers=u["headers"]).status_code == 204
    assert list(Path(settings.upload_dir).iterdir()) == []
    assert client.get(f"/api/files/{f['id']}", headers=u["headers"]).status_code == 404


def test_rejects_bad_files(client, make_client_user, monkeypatch):
    u = make_client_user()
    h = u["headers"]
    assert upload(client, h, "virus.exe", b"MZ" + b"0" * 50, "application/x-msdownload").status_code == 422
    # розширення png, але заявлений MIME інший
    assert upload(client, h, "a.png", PNG, "text/plain").status_code == 422
    # розширення й MIME правильні, а вміст підроблений
    assert upload(client, h, "fake.png", b"just text, not an image", "image/png").status_code == 422
    assert upload(client, h, "empty.png", b"", "image/png").status_code == 422

    monkeypatch.setattr(settings, "max_file_size", 100)
    big = upload(client, h, "big.png", PNG + b"0" * 200, "image/png")
    assert big.status_code == 413
    assert list(Path(settings.upload_dir).iterdir()) == []  # недозавантажений файл не лишився


def test_original_name_never_used_as_path(client, make_client_user):
    u = make_client_user()
    r = upload(client, u["headers"], name="../../evil.png")
    assert r.status_code == 201
    files = list(Path(settings.upload_dir).iterdir())
    assert len(files) == 1 and files[0].parent == Path(settings.upload_dir)
    assert files[0].name != "evil.png"


def test_multiple_upload_all_or_nothing(client, make_client_user):
    u = make_client_user()
    ok = client.post(
        "/api/files/upload-multiple", headers=u["headers"],
        files=[("files", ("a.png", PNG, "image/png")), ("files", ("b.pdf", PDF, "application/pdf"))],
    )
    assert ok.status_code == 201 and len(ok.json()) == 2

    bad = client.post(
        "/api/files/upload-multiple", headers=u["headers"],
        files=[("files", ("c.png", PNG, "image/png")), ("files", ("d.exe", b"MZ00", "application/octet-stream"))],
    )
    assert bad.status_code == 422
    assert len(list(Path(settings.upload_dir).iterdir())) == 2  # попередній файл із невдалої пачки прибрано
    assert client.get("/api/files", headers=u["headers"]).json()["total"] == 2

    many = client.post(
        "/api/files/upload-multiple", headers=u["headers"],
        files=[("files", (f"{i}.png", PNG, "image/png")) for i in range(6)],
    )
    assert many.status_code == 422


def test_access_control(client, admin, make_client_user):
    a = make_client_user("a@example.com")
    b = make_client_user("b@example.com")
    f = upload(client, a["headers"]).json()

    assert client.get(f"/api/files/{f['id']}", headers=b["headers"]).status_code == 403
    assert client.delete(f"/api/files/{f['id']}", headers=b["headers"]).status_code == 403
    assert client.get("/api/files", headers=b["headers"]).json()["total"] == 0
    assert client.get(f"/api/files/{f['id']}", headers=admin["headers"]).status_code == 200


def test_attach_file_to_car(client, make_client_user):
    a = make_client_user("a@example.com")
    b = make_client_user("b@example.com")
    car = make_car(client, a["headers"], "AA1111AA")

    assert upload(client, b["headers"], car_id=str(car["id"])).status_code == 403
    r = upload(client, a["headers"], car_id=str(car["id"]))
    assert r.status_code == 201 and r.json()["car_id"] == car["id"]
    by_car = client.get("/api/files", headers=a["headers"], params={"car_id": car["id"]}).json()
    assert by_car["total"] == 1
