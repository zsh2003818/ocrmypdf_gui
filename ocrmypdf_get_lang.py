import os
import requests
import subprocess

# languages you want to install
languages = ["lat", "grc", "deu", "fra", "ita", "chi_sim", "chi_tra", "chi_tra_vert", "chi_sim_vert", "spa", "vie"]

# repository for high-accuracy models
BASE_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main"

def get_tessdata_path():
    result = subprocess.run(
        ["tesseract", "--list-langs"],
        capture_output=True,
        text=True
    )

    first_line = result.stdout.splitlines()[0]
    path = first_line.split('"')[1]
    print(path)
    return path

def download_language(lang, tessdata_path):
    url = f"{BASE_URL}/{lang}.traineddata"
    dest = os.path.join(tessdata_path, f"{lang}.traineddata")

    if os.path.exists(dest):
        print(f"{lang} already installed")
        return

    print(f"Downloading {lang}...")
    r = requests.get(url)

    with open(dest, "wb") as f:
        f.write(r.content)

    print(f"{lang} installed")

def main():
    tessdata_path = get_tessdata_path()
    print("Tessdata directory:", tessdata_path)

    for lang in languages:
        download_language(lang, tessdata_path)

    print("Done.")

if __name__ == "__main__":
    main()
