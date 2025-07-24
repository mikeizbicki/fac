#!/usr/bin/env python3

import argparse
from pdfminer.high_level import extract_text

def main():
    parser = argparse.ArgumentParser(description='Extract text from PDF file')
    parser.add_argument('input_pdf', help='Input PDF file path')
    parser.add_argument('output_txt', help='Output text file path')

    args = parser.parse_args()

    text = extract_text(args.input_pdf)
    with open(args.output_txt, 'w', encoding='utf-8') as f:
        f.write(text)

if __name__ == '__main__':
    main()
