from os import makedirs
from os.path import splitext, join

from .config import TEST_SPLIT, TRAIN_SPLIT


def split(json_paths, verbose=True):
    """Splits amazon datasets into train.json, val.json and test.json in separate folder
    according to split rates defined in constants.py

    Arguments:
        json_paths: list of strings - paths to dataset jsons
        verbose: bool — prints current status of processing is True

    Returns:
        None
    """
    for json_path in json_paths:
        if verbose:
            print('Reading %s...' % json_path)
        data = []
        with open(json_path) as f:
            for line in f:
                if "\"overall\":" in line and "\"reviewerID\":" in line and "\"asin\":" in line and "\"reviewText\":" in line:
                    assert line[0] == '{' and line[-2] == '}'
                    data.append(line)
                else:
                    print(line)
        train_json_path = join(splitext(json_path)[0], 'train.json')
        test_json_path = join(splitext(json_path)[0], 'test.json')
        val_json_path = join(splitext(json_path)[0], 'val.json')
        makedirs(splitext(json_path)[0], exist_ok=True)

        with open(train_json_path, 'w') as f:
            f.writelines(
                data[:int(TRAIN_SPLIT * len(data))]
            )
        if verbose:
            print(train_json_path + ' written')

        with open(test_json_path, 'w') as f:
            f.writelines(
                data[int(TRAIN_SPLIT * len(data)):int((TRAIN_SPLIT + TEST_SPLIT) * len(data))]
            )
        if verbose:
            print(test_json_path + ' written')

        with open(val_json_path, 'w') as f:
            f.writelines(
                data[int((TRAIN_SPLIT + TEST_SPLIT) * len(data)):]
            )
        if verbose:
            print(val_json_path + ' written')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--data_dir', type=str, default='./data/Musical_Instruments_5_2018.json', help='The path of the json data file')
    args = parser.parse_args()

    json_paths = [args.data_dir]
    split(json_paths)
