from openpyxl import Workbook

from web_scraper.config import Settings
from web_scraper.sheets import load_image_jobs


def _settings(root_dir):
    settings = Settings(root_dir=root_dir)
    settings.sheet.image_slot_patterns = [r"^base_\d+$", r"^side_\d+$"]
    settings.sheet.source_url_columns = ["officialMediaUrl", "amazonUrl"]
    return settings


def test_load_image_jobs_creates_one_job_per_image_slot(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["sku", "productName", "base_1", "side_1", "officialMediaUrl"])
    sheet.append(["ABC123", "Phone X", "", "", "https://brand.example.com/device"])
    workbook_path = tmp_path / "sheet.xlsx"
    workbook.save(workbook_path)

    jobs = load_image_jobs(workbook_path, _settings(tmp_path))

    assert [job.attribute_name for job in jobs] == ["base_1", "side_1"]
    assert all(job.row_number == 2 for job in jobs)
    assert jobs[0].metadata["officialmediaurl"] == "https://brand.example.com/device"
