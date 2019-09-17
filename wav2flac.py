from logging import basicConfig, getLogger, FileHandler, Formatter, StreamHandler, BASIC_FORMAT, DEBUG, INFO
from os import chdir, listdir, makedirs, path, remove, sep as os_sep, unlink
import re
from shutil import copyfile
import subprocess
from tempfile import mkstemp
import yaml

from tagflac.tagflac import metaflac_dir

logger = getLogger(__name__)

def read_yaml(filepath):
    with open(filepath) as fp:
        ret = yaml.safe_load(fp)
        if ret is None:
            return {}
        else:
            return ret
    raise Exception(f'Read yaml file failed: {filepath}')

def strip_bs(string):
    import re
    string_split_bs = re.split(r'([\b]+)', string)
    string_split_nobs = []
    for idx, ele in enumerate(string_split_bs):
        if idx + 1 < len(string_split_bs):
            next_ele = string_split_bs[idx + 1]
            if re.match(r'^[\b]+$', next_ele):
                string_split_nobs.append(ele[:len(ele)-len(next_ele)])
        elif not re.match(r'^[\b]+$', ele):
            string_split_nobs.append(ele)
    return ''.join(string_split_nobs)

def log_multi_lines(logger, line_with_newlines, *, level=INFO):
    for line in line_with_newlines.split('\n'):
        logger.log(level, f'> {line}')

def strip_cr(filepath):
    _, temp = mkstemp()
    copyfile(filepath, temp)
    with open(temp, 'r', newline='\n') as fp_in:
        with open(filepath, 'w', newline='\n') as fp_out:
            for line in fp_in:
                fp_out.write(re.sub(r'\r$', '', line))
    unlink(temp)

def split_to_flac(indir, outdir, config):
    shntool = config.get('shntool')
    if shntool is None:
        shntool = 'shntool'
    else:
        shntool = path.expanduser(shntool)

    wavfile = path.join(indir, 'a.wav')
    cuefile = path.join(indir, 'a.cue')
    logger.info(f'Splitting {wavfile} using shntool')
    logfile = path.join(outdir, 'shnsplit.log')
    with open(logfile, 'w') as fp:
        outdir_rel, cuefile_rel, wavfile_rel = [path.relpath(e, outdir) for e in [outdir, cuefile, wavfile]]
        shnsplit_process = subprocess.run([shntool, 'split', '-O', 'always', '-d', outdir_rel, '-o', 'flac', '-f', cuefile_rel, '-t', '%n', wavfile_rel], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=outdir)
        shnsplit_output = shnsplit_process.stdout.decode('utf-8')
        shnsplit_output = strip_bs(shnsplit_output)
        fp.write(shnsplit_output)
        log_multi_lines(logger, shnsplit_output)

        if 'warning: file 1 will be too short to be burned' in shnsplit_output:
            short_file = path.join(outdir, '00.flac')
            logstr = f'Removing 00.flac'
            logger.info(logstr)
            fp.write(logstr)
            remove(short_file)

    strip_cr(logfile)

def copy_image(indir, outdir):
    meta = read_yaml(path.join(indir, 'meta.yml'))

    img = meta.get('img', [{}])[0]
    src = img.get('src')
    filename = None
    if src is not None:
        matchOB = re.match('^.*/([^/?]*)', src)
        if matchOB:
            filename = matchOB.group(1)
    if filename is None:
        filename = img.get('filename')

    logfile = path.join(outdir, 'image.log')
    with open(logfile, 'w') as fp:
        if filename is not None:
            _, ext = path.splitext(filename)
            if ext in ['.jpg', 'jpeg', '.JPG', 'JPEG']:
                ext = '.jpg'
            infile = path.join(indir, filename)
            outfile = path.join(outdir, f'folder{ext}')
            infile_rel, outfile_rel = [path.relpath(e, outdir) for e in [infile, outfile]]
            logstr = f'Copying {infile_rel} to {outfile_rel}'
            logger.info(logstr)
            fp.write(logstr)
            copyfile(infile, outfile)

    strip_cr(logfile)

def tagflac(indir, outdir, config):
    logger_tagflac = getLogger('tagflac.tagflac')

    convert_config = config.get('convert_config', path.join(path.dirname(__file__), 'tagflac/tests/data/metaflac_real_world01/convert.yml'))
    convert_config = path.expanduser(convert_config)

    handler = FileHandler(filename=path.join(outdir, 'tagflac.log'), mode='w')
    handler.setFormatter(Formatter(BASIC_FORMAT))
    logger_tagflac.addHandler(handler)

    tag_list = read_yaml(path.join(indir, 'tags.yml'))
    convert_dict = read_yaml(convert_config)
    metaflac_dir(outdir, tag_list, convert_dict)

    logger_tagflac.removeHandler(handler)

def metaflac(outdir, config):
    metaflac = config.get('metaflac')
    if metaflac is None:
        metaflac = 'metaflac'
    else:
        metaflac = path.expanduser(metaflac)

    flacfiles = [e for e in listdir(outdir) if e.endswith('.flac')]
    flacfiles = sorted(flacfiles)
    logfile = path.join(outdir, 'metaflac.log')
    with open(logfile, 'w') as fp:
        metaflac_list_process = subprocess.run([metaflac, '--list', '--block-type=VORBIS_COMMENT', *flacfiles], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=outdir)
        metaflac_list_output = metaflac_list_process.stdout.decode('utf-8')
        log_multi_lines(logger, metaflac_list_output)
        fp.write(metaflac_list_output)

    strip_cr(logfile)

def calculate_outdir(indir):
    indir_separated = re.split(os_sep, path.abspath(indir))
    for idx in reversed(range(len(indir_separated))):
        if indir_separated[idx] == 'wav':
            indir_separated[idx] = 'flac'
            break
    return os_sep.join(indir_separated)

def execute(indir, outdir, config, no_convert, no_overwrite, files_to_check):
    if outdir is None:
        outdir = calculate_outdir(indir)

    for file_to_check in files_to_check:
        filepath = path.join(indir, file_to_check)
        if not path.isfile(filepath):
            logger.warn(f'File not found: {file_to_check}; Skip {indir}')
            return

    # Generate FLAC files
    if no_overwrite:
        if path.isdir(outdir):
            logger.warn(f'Output directory has already existed: {outdir}')
            return

    if not no_convert:
        makedirs(outdir, exist_ok=True)
        split_to_flac(indir, outdir, config)

    # Edit FLAC files and copy cover image file
    copy_image(indir, outdir)
    tagflac(indir, outdir, config)
    metaflac(outdir, config)

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument(
        '--outdir',
        metavar='outdir',
        type=str,
        help='Output directory'
    )
    parser.add_argument(
        '--config',
        type=argparse.FileType('r'),
        help='Config file'
    )
    parser.add_argument(
        '--no-convert',
        action='store_true',
        help='Do not convert from wav to flac. Only modify tags and images'
    )
    parser.add_argument(
        '--no-overwrite',
        action='store_true',
        help='Do nothing if the output directory already exists'
    )
    parser.add_argument(
        'indirs',
        metavar='indirs',
        type=str,
        nargs='+',
        help='Input directory'
    )

    args = parser.parse_args()

    if args.config is None:
        config = read_yaml(path.join(path.dirname(__file__), 'config.yml'))
    else:
        config = yaml.safe_load(args.config)
        if config is None:
            config = {}

    files_to_check = ['meta.yml', 'tags.yml']
    if not args.no_convert:
        files_to_check.extend(['a.cue', 'a.wav'])

    indirs = args.indirs
    outdir = args.outdir
    no_overwrite = args.no_overwrite
    no_convert = args.no_convert

    if outdir is not None and len(indirs) > 1:
        raise Exception('More than one indirs were specified with one outdir (only one indir sholud be specified).')

    for indir in indirs:
        indir = path.expanduser(indir)
        execute(indir, outdir, config, no_convert, no_overwrite, files_to_check)

if __name__ == '__main__':
    basicConfig(level=DEBUG)
    main()
