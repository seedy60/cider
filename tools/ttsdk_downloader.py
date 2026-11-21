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



def get_platform_patterns() -> list[str]:
    """Regexes matching this platform's SDK archive, most preferred first.

    bearware.dk renames the platform part of the archive between releases (the Linux
    x86_64 build was ``ubuntu22_x86_64`` and later became ``ubuntu26_x86_64``), so the
    archive name is matched by platform family instead of one pinned name.
    """
    machine = platform.machine()
    if sys.platform == "win32":
        architecture = platform.architecture()
        if machine == "AMD64" or machine == "x86":
            if architecture[0] == "64bit":
                return [r"_win64\.7z$"]
            else:
                return [r"_win32\.7z$"]
        else:
            sys.exit("Native Windows on ARM is not supported")
    elif sys.platform == "darwin":
        sys.exit("Darwin is not supported")
    else:
        if machine == "AMD64" or machine == "x86_64":
            return [r"_(?:ubuntu|linux|debian)[a-z0-9_]*x86_64\.7z$"]
        elif machine in ("aarch64", "arm64"):
            # The SDK only ships a 64-bit ARM build; 32-bit armhf is no longer offered.
            return [r"_(?:raspbian|ubuntu|linux|debian)[a-z0-9_]*arm64\.7z$"]
        else:
            sys.exit("Your architecture is not supported")


# The Linux SDK archives are built against a specific Ubuntu release, so each one
# requires at least that release's glibc. Planting the wrong build on an older
# distribution fails at import time with "version `GLIBC_x.y' not found".
UBUNTU_REQUIRED_GLIBC = {
    "ubuntu22": (2, 35),
    "ubuntu24": (2, 39),
    "ubuntu26": (2, 43),
}


def _local_glibc_version() -> tuple[int, int] | None:
    """Return the local glibc version as (major, minor), or None when unknown."""
    libc, version = platform.libc_ver()
    if libc != "glibc":
        return None
    try:
        major, minor = version.split(".")[:2]
        return (int(major), int(minor))
    except ValueError:
        return None


def _required_glibc(archive: str) -> tuple[int, int] | None:
    """Return the glibc an "ubuntuNN" SDK archive needs, or None if it is not gated."""
    match = re.search(r"(ubuntu\d+)", archive)
    if not match:
        return None
    # An Ubuntu release this table doesn't know about is newer than anything listed
    # here, so assume it needs more than the machine is likely to have.
    return UBUNTU_REQUIRED_GLIBC.get(match.group(1), (99, 0))


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


def list_versions(session: requests.Session) -> list[str]:
    """Return the SDK version folders listed on the index page, newest first."""
    response = _get(session, url)
    response.raise_for_status()
    page = bs4.BeautifulSoup(response.text, features="html.parser")
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

    def version_key(name: str) -> tuple:
        match = re.match(r"v(\d+)\.(\d+)([a-z]*)", name)
        return (int(match.group(1)), int(match.group(2)), match.group(3))

    return sorted(versions, key=version_key, reverse=True)


def find_download_url(session: requests.Session, versions: list[str]) -> str:
    """Return the archive URL for this platform in the newest version that ships one.

    Newest SDK version wins, but only among builds whose glibc requirement this
    machine satisfies; within a version the most recent compatible build is used.
    """
    patterns = [re.compile(pattern) for pattern in get_platform_patterns()]
    local_glibc = _local_glibc_version()
    for version in versions:
        response = _get(session, f"{url}/{version}/")
        if not response.ok:
            continue
        page = bs4.BeautifulSoup(response.text, features="html.parser")
        names = [
            link.get("href", "")
            for link in page.find_all("a", href=True)
            if link.get("href", "").startswith("tt5sdk_")
            and link.get("href", "").endswith(".7z")
        ]
        for pattern in patterns:
            compatible = []
            for name in names:
                if not pattern.search(name):
                    continue
                required = _required_glibc(name)
                if required is not None and local_glibc is not None:
                    if required > local_glibc:
                        continue
                    compatible.append((required, name))
                else:
                    compatible.append(((0, 0), name))
            if compatible:
                return f"{url}/{version}/{max(compatible)[1]}"
    local = "glibc " + ".".join(str(part) for part in local_glibc) if local_glibc else "unknown libc"
    sys.exit(
        f"Could not find a TeamTalk SDK archive for this platform ({local}) at {url}"
    )


def download() -> None:
    session = create_session()
    versions = list_versions(session)
    if not versions:
        sys.exit("Could not find any TeamTalk SDK versions at " + url)
    download_url = find_download_url(session, versions)
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
