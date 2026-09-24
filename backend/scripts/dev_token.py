"""Issue a short-lived local demo JWT using a private key kept outside Git."""

import argparse
import base64
import json
import subprocess
import time
import uuid
from pathlib import Path


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--tenant-id", type=uuid.UUID, required=True)
    parser.add_argument("--role", choices=["admin", "viewer"], default="admin")
    parser.add_argument(
        "--private-key", type=Path, default=Path("config/auth-private.pem")
    )
    parser.add_argument("--issuer", default="enterprise-agent-platform")
    parser.add_argument("--audience", default="enterprise-agent-api")
    args = parser.parse_args()
    now = int(time.time())
    header = base64url(
        json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    claims = {
        "sub": args.subject,
        "tenant_id": str(args.tenant_id),
        "role": args.role,
        "iss": args.issuer,
        "aud": args.audience,
        "iat": now,
        "exp": now + 3600,
    }
    payload = base64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(args.private_key)],
        input=signing_input,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    print(f"{header}.{payload}.{base64url(signature)}")


if __name__ == "__main__":
    main()
