import pytest
from PIL import Image, ImageChops, ImageOps

from pixsift.editor import ORIENTATION, Crop, EditRequest, apply_edit


def gradient(path, size=(64, 32), orientation=None):
    img = Image.new("RGB", size)
    img.putdata([(x * 4 % 256, y * 8 % 256, (x + y) % 256) for y in range(size[1]) for x in range(size[0])])
    exif = Image.Exif()
    if orientation:
        exif[ORIENTATION] = orientation
    img.save(path, "JPEG", quality=95, exif=exif)
    return path


def displayed(path):
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


@pytest.mark.parametrize("orientation", [None, 3, 6, 8])
@pytest.mark.parametrize("rotate,flip_h", [(90, False), (180, False), (270, True), (0, True)])
def test_jpeg_rotate_is_lossless_and_correct(tmp_path, orientation, rotate, flip_h):
    src = gradient(tmp_path / "a.jpg", orientation=orientation)
    req = EditRequest(rotate=rotate, flip_h=flip_h)
    out = apply_edit(str(src), req, tmp_path / "bk")
    assert out.name == "a_edited.jpg" and src.exists()
    # Compressed pixel data untouched: only the orientation tag changed.
    with Image.open(src) as a, Image.open(out) as b:
        assert ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is None
    expected = displayed(src).rotate(-rotate, expand=True)
    if flip_h:
        expected = ImageOps.mirror(expected)
    assert displayed(out).tobytes() == expected.tobytes()


def test_crop_and_adjust_saves_copy(tmp_path):
    src = gradient(tmp_path / "b.jpg", size=(100, 50))
    req = EditRequest(rotate=90, crop=Crop(x=0, y=0.5, w=1, h=0.5), brightness=1.3)
    out = apply_edit(str(src), req, tmp_path / "bk")
    with Image.open(out) as im:
        assert im.size == (50, 50)
        assert im.getexif().get(ORIENTATION, 1) == 1


def test_overwrite_keeps_backup_and_numbered_copies(tmp_path):
    src = gradient(tmp_path / "c.jpg")
    apply_edit(str(src), EditRequest(rotate=90), tmp_path / "bk")
    second = apply_edit(str(src), EditRequest(rotate=90), tmp_path / "bk")
    assert second.name == "c_edited-2.jpg"
    out = apply_edit(str(src), EditRequest(contrast=1.5, mode="overwrite"), tmp_path / "bk")
    assert out == src and len(list((tmp_path / "bk").iterdir())) == 1


def test_png_edit_keeps_format(tmp_path):
    src = tmp_path / "d.png"
    Image.new("RGBA", (40, 20), (255, 0, 0, 128)).save(src)
    out = apply_edit(str(src), EditRequest(flip_v=True, saturation=0.5), tmp_path / "bk")
    assert out.suffix == ".png" and Image.open(out).size == (40, 20)


def test_crop_outside_rejected():
    with pytest.raises(ValueError):
        EditRequest(crop=Crop(x=0.5, y=0, w=0.8, h=1))


def test_lossless_overwrite_replaces_the_original_in_place(tmp_path):
    # The source must be closed before it's replaced (Windows refuses to replace open files).
    src = gradient(tmp_path / "e.jpg")
    out = apply_edit(str(src), EditRequest(rotate=90, mode="overwrite"), tmp_path / "bk")
    assert out == src
    with Image.open(src) as im:
        assert im.getexif()[ORIENTATION] == 6
