from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cloud_inference_server.cli import main
from cloud_inference_server.config import load_config


def test_cli_set_root_key_persists(tmp_path):
    config_path = tmp_path / "cloud.config.json"
    root_value = "FSK-ROOT-1234567890abcdef"

    exit_code = main(["--config", str(config_path), "set-root-key", root_value])
    assert exit_code == 0

    config = load_config(config_path)
    assert config.root_key == root_value
