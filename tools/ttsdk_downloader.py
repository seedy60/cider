#!/usr/bin/env python3

import bs4
import patoolib
import requests

import hashlib
import os
import platform
import re
import shutil
import sys
from urllib.parse import urlsplit


url = "https://bearware.dk/teamtalksdk"



def get_url_suffix_from_platform() -> str:
    machine = platform.machine()
    if sys.platform == "win32":
        architecture = platform.architecture()
        if machine == "AMD64" or machine == "x86":
            if architecture[0] == "64bit":
                return "win64"
            else:
                return "win32"
        else:
            sys.exit("Native Windows on ARM is not supported")
    elif sys.platform == "darwin":
        sys.exit("Darwin is not supported")
    else:
        if machine == "AMD64" or machine == "x86_64":
            return "ubuntu22_x86_64"
        elif machine in ("aarch64", "arm64"):
            # The SDK only ships a 64-bit ARM build; 32-bit armhf is no longer offered.
            return "raspbian_arm64"
        else:
            sys.exit("Your architecture is not supported")


def _leading_zero_bits(digest_hex: str) -> int:
    bits = 0
    for char in digest_hex:
        value = int(char, 16)
        if value == 0:
            bits += 4
        else:
            bits += 3 if value < 2 else 2 if value < 4 else 1 if value < 8 else 0
            break
    return bits


def _solve_challenge(session: requests.Session, response: requests.Response) -> bool:
    """Solve bearware.dk's proof-of-work firewall and store the clearance cookie.

    bearware.dk sits behind a JavaScript "browser check" (HTTP 454). The check is a
    SHA-256 proof of work: find a nonce whose hash of "<token>:<nonce>" has D leading
    zero bits, POST it to /.sc-verify/, and reuse the returned clearance cookie. This
    performs the same work a browser would. Returns True when a challenge was solved.
    """
    challenge = re.search(r'var T="([0-9a-f]+)",TS="(\d+)",D=(\d+);', response.text)
    if not challenge:
        return False
    token, timestamp, difficulty = challenge.group(1), challenge.group(2), int(challenge.group(3))
    nonce = 0
    while _leading_zero_bits(hashlib.sha256(f"{token}:{nonce}".encode()).hexdigest()) < difficulty:
        nonce += 1
    parts = urlsplit(response.url)
    verify = session.post(
        f"{parts.scheme}://{parts.netloc}/.sc-verify/",
        data={"ts": timestamp, "nonce": str(nonce), "token": token},
    )
    clearance = verify.json().get("cookie") if verify.ok else None
    if not clearance:
        return False
    session.cookies.set("sc_clearance", clearance, domain=parts.netloc)
    return True


def _get(session: requests.Session, target: str, **kwargs) -> requests.Response:
    """GET that transparently clears bearware.dk's firewall (HTTP 454) and retries."""
    response = session.get(target, **kwargs)
    if response.status_code == 454 and _solve_challenge(session, response):
        response.close()
        response = session.get(target, **kwargs)
    return response


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36'})
    return session


def download() -> None:
    session = create_session()
    r = _get(session, url)
    page = bs4.BeautifulSoup(r.text, features="html.parser")
    # bearware.dk only keeps a rolling window of recent SDK versions, so select the
    # newest "vX.Y" folder available instead of pinning to a specific series.
    versions = []
    for item in page.find_all("li"):
        link = item.a
        if link is None:
            continue
        href = link.get("href")
        if href and re.match(r"v\d+\.\d+", href):
            versions.append(href.rstrip("/"))
    if not versions:
        sys.exit("Could not find any TeamTalk SDK versions at " + url)

    def version_key(name: str) -> tuple:
        match = re.match(r"v(\d+)\.(\d+)([a-z]*)", name)
        return (int(match.group(1)), int(match.group(2)), match.group(3))

    version = max(versions, key=version_key)
    download_url = (
        url
        + "/"
        + version
        + "/"
        + "tt5sdk_{v}_{p}.7z".format(v=version, p=get_url_suffix_from_platform())
    )
    print("Downloading from " + download_url)
    with _get(session, download_url, stream=True) as response:
        response.raise_for_status()
        with open(os.path.join(os.getcwd(), "ttsdk.7z"), "wb") as archive:
            for chunk in response.iter_content(chunk_size=65536):
                archive.write(chunk)


def extract() -> None:
    try:
        os.mkdir(os.path.join(os.getcwd(), "ttsdk"))
    except FileExistsError:
        shutil.rmtree(os.path.join(os.getcwd(), "ttsdk"))
        os.mkdir(os.path.join(os.getcwd(), "ttsdk"))
    patoolib.extract_archive(
        os.path.join(os.getcwd(), "ttsdk.7z"), outdir=os.path.join(os.getcwd(), "ttsdk")
    )

def move() -> None:
    path = os.path.join(os.getcwd(), "ttsdk", os.listdir(os.path.join(os.getcwd(), "ttsdk"))[0])
    libraries = ["TeamTalk_DLL", "TeamTalkPy"]
    dest_dir = os.path.join(os.getcwd(), os.pardir) if os.path.basename(os.getcwd()) == "tools" else os.getcwd()
    for library in libraries:
        try:
            os.rename(
                os.path.join(path, "Library", library), os.path.join(dest_dir, library)
            )
        except OSError:
            shutil.rmtree(os.path.join(dest_dir, library))
            os.rename(
                os.path.join(path, "Library", library), os.path.join(dest_dir, library)
            )
    try:
        os.rename(
            os.path.join(path, "License.txt"), os.path.join(dest_dir, "TTSDK_license.txt")
        )
    except FileExistsError:
        os.remove(os.path.join(dest_dir, "TTSDK_license.txt"))
        os.rename(
            os.path.join(path, "License.txt"), os.path.join(dest_dir, "TTSDK_license.txt")
        )


def clean() -> None:
    os.remove(os.path.join(os.getcwd(), "ttsdk.7z"))
    shutil.rmtree(os.path.join(os.getcwd(), "ttsdk"))


def install() -> None:
    print("Installing TeamTalk sdk components")
    print("Downloading latest sdk version")
    download()
    print("Downloaded. extracting")
    extract()
    print("Extracted. moving")
    move()
    print("moved. cleaning")
    clean()
    print("cleaned.")
    print("Installed, exiting.")

if __name__ == "__main__":
    install()
