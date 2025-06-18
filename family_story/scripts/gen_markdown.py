#!/usr/bin/env python3

import glob
import json

# setup logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


if __name__ == '__main__':

    # parse command line options
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('book_path')
    args = parser.parse_args()

    out_path = args.book_path + '/text.md'
    logging.info(f"out_path={out_path}")
    with open(out_path, 'wt') as fout:

        for chapter_num, chapter_path in enumerate(sorted(glob.glob(args.book_path + '/chapter*/chapter.json'))):
            logging.info(f"chapter_path={chapter_path}")

            print(f"chapter_path={chapter_path}")
            with open(chapter_path) as fin:
                chapter_json = json.load(fin)

            fout.write(f"## Chapter {chapter_num}: {chapter_json['name']} \n\n")
            for section_num, section in enumerate(chapter_json['sections']):
                fout.write(f"### Section {section_num}: {section.get('title_target')} \n\n")
                image_description = section.get('image_description', '')
                fout.write(f"![image_description](scenes/{section['sublocation']}.png \"{image_description}\") \n\n")

                text = section.get('text', '')
                fout.write(f"{text} \n\n")

            fout.flush()
