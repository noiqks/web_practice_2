import argparse
import hashlib
from pathlib import Path


def calculate_md5(input_path):
    md5_hash = hashlib.md5()

    with open(input_path, "rb") as input_file:
        while True:
            chunk = input_file.read(4096)
            if not chunk:
                break
            md5_hash.update(chunk)

    return md5_hash.hexdigest()


def main():
    parser = argparse.ArgumentParser(
        description="Calculate the MD5 hash of a file."
    )
    parser.add_argument("input_file", help="Path to the input file")
    parser.add_argument("output_file", help="Path to the result file")
    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_path = Path(args.output_file)

    if not input_path.is_file():
        parser.error("Input file does not exist.")

    result = calculate_md5(input_path)
    output_path.write_text(result + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
