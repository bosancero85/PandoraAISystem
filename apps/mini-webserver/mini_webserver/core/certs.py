"""Zertifikate für HTTPS im lokalen Netzwerk.

Browser geben Mikrofon und Spracherkennung nur auf sicheren Adressen frei (https:// oder localhost).
Dieses Modul erzeugt dafür eine eigene kleine Zertifizierungsstelle (CA) und ein Server-Zertifikat,
das für den Rechnernamen und die aktuelle IP-Adresse gilt.

- Die CA bleibt gleich. Wird sie einmal auf dem Handy installiert, vertraut das Handy auch allen
  späteren Server-Zertifikaten (zum Beispiel nach einer neuen IP-Adresse).
- Das Server-Zertifikat wird bei Bedarf automatisch neu ausgestellt.
"""
from __future__ import annotations

import datetime
import ipaddress
import os
from dataclasses import dataclass
from typing import Iterable, List, Set, Tuple

CA_FILE = "mini-webserver-ca.pem"
CA_KEY_FILE = "mini-webserver-ca.key"
CERT_FILE = "server.pem"
KEY_FILE = "server.key"

CA_DAYS = 3650
CERT_DAYS = 800          # iOS und macOS akzeptieren für eigene CAs höchstens 825 Tage
RENEW_BEFORE_DAYS = 30


class CertError(Exception):
    """Fehler mit einer Meldung, die direkt angezeigt werden kann."""


@dataclass(frozen=True)
class CertPaths:
    ca_cert: str
    cert: str
    key: str


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as exc:  # pragma: no cover - hängt von der Installation ab
        raise CertError("Für HTTPS fehlt das Paket „cryptography“. Installiere es mit: pip install cryptography") from exc
    return x509, hashes, serialization, rsa, ExtendedKeyUsageOID, NameOID


def split_hosts(hosts: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Trennt Namen und IP-Adressen. Doppelte und leere Einträge fallen weg, die Reihenfolge bleibt."""
    names: List[str] = []
    ips: List[str] = []
    for raw in hosts:
        host = str(raw or "").strip()
        if not host:
            continue
        try:
            ip = str(ipaddress.ip_address(host))
        except ValueError:
            host = host.lower()
            if host not in names:
                names.append(host)
        else:
            if ip not in ips:
                ips.append(ip)
    return names, ips


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _write(path: str, data: bytes, private: bool = False) -> None:
    with open(path, "wb") as handle:
        handle.write(data)
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _read_cert(path: str):
    x509, *_ = _crypto()
    try:
        with open(path, "rb") as handle:
            return x509.load_pem_x509_certificate(handle.read())
    except (OSError, ValueError):
        return None


def _expires_soon(cert) -> bool:
    return cert.not_valid_after_utc - _now() < datetime.timedelta(days=RENEW_BEFORE_DAYS)


def cert_hosts(path: str) -> Set[str]:
    """Namen und IP-Adressen, für die das Zertifikat gilt (leer, wenn es sich nicht lesen lässt)."""
    x509, *_ = _crypto()
    cert = _read_cert(path)
    if cert is None:
        return set()
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return set()
    found = {n.lower() for n in san.get_values_for_type(x509.DNSName)}
    found |= {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    return found


def _new_key(rsa):
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem_key(serialization, key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption())


def _create_ca(directory: str):
    x509, hashes, serialization, rsa, _eku, NameOID = _crypto()
    key = _new_key(rsa)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mini Webserver Lokale CA"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Mini Webserver")])
    now = _now()
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write(os.path.join(directory, CA_KEY_FILE), _pem_key(serialization, key), private=True)
    _write(os.path.join(directory, CA_FILE), cert.public_bytes(serialization.Encoding.PEM))
    return cert, key


def _load_ca(directory: str):
    _x509, _hashes, serialization, *_ = _crypto()
    cert = _read_cert(os.path.join(directory, CA_FILE))
    if cert is None or _expires_soon(cert):
        return None
    try:
        with open(os.path.join(directory, CA_KEY_FILE), "rb") as handle:
            key = serialization.load_pem_private_key(handle.read(), password=None)
    except (OSError, ValueError, TypeError):
        return None
    return cert, key


def _create_server_cert(directory: str, ca_cert, ca_key, names: List[str], ips: List[str]) -> None:
    x509, hashes, serialization, rsa, ExtendedKeyUsageOID, NameOID = _crypto()
    key = _new_key(rsa)
    now = _now()
    alt = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    common = names[0] if names else ips[0]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=CERT_DAYS))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True,
                                         content_commitment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write(os.path.join(directory, KEY_FILE), _pem_key(serialization, key), private=True)
    _write(os.path.join(directory, CERT_FILE), cert.public_bytes(serialization.Encoding.PEM))


def ensure_certificates(directory: str, hosts: Iterable[str]) -> Tuple[CertPaths, bool]:
    """Stellt sicher, dass CA und passendes Server-Zertifikat im Ordner liegen.

    `hosts` sind Namen und IP-Adressen, unter denen der Server erreichbar ist. „localhost“ und
    127.0.0.1 kommen immer dazu. Rückgabe: (Pfade, True wenn ein neues Server-Zertifikat entstand).
    """
    names, ips = split_hosts(list(hosts) + ["localhost", "127.0.0.1"])
    wanted = set(names) | set(ips)
    try:
        os.makedirs(directory, exist_ok=True)
        ca = _load_ca(directory)
        if ca is None:
            ca = _create_ca(directory)
            # Eine neue CA macht alte Server-Zertifikate wertlos.
            for stale in (CERT_FILE, KEY_FILE):
                try:
                    os.remove(os.path.join(directory, stale))
                except OSError:
                    pass
        paths = CertPaths(os.path.join(directory, CA_FILE), os.path.join(directory, CERT_FILE),
                          os.path.join(directory, KEY_FILE))
        current = _read_cert(paths.cert)
        fresh = (current is not None and os.path.isfile(paths.key)
                 and wanted <= cert_hosts(paths.cert) and not _expires_soon(current))
        if fresh:
            return paths, False
        _create_server_cert(directory, ca[0], ca[1], names, ips)
        return paths, True
    except OSError as exc:
        raise CertError("Zertifikate konnten nicht angelegt werden: %s" % exc) from exc
