"""Publish only the match counters needed by the player page."""
from pathlib import Path
import argparse
import json
import os


def public_counters(source):
    result={key:source[key] for key in ('updated_utc','map','phase','seconds_remaining','bots','players','human_capacity')}
    result['teams']=[{key:team[key] for key in ('id','points','bots','players','repair_pads')}
                     for team in source['teams']]
    if sorted(team['id'] for team in result['teams']) != [1,2]:
        raise ValueError('Expected exactly two teams')
    for key in ('bots','players','human_capacity'):
        if type(result[key]) is not int or not 0 <= result[key] <= 128:
            raise ValueError('Invalid player counts')
    return result


def publish(source, destination):
    if source.stat().st_size > 65536:
        raise ValueError('Unexpected status size')
    document=public_counters(json.loads(source.read_text()))
    temporary=destination.with_name(f'.status-{os.getpid()}.tmp')
    temporary.write_text(json.dumps(document)+'\n',encoding='utf-8')
    temporary.chmod(0o644)
    os.replace(temporary,destination)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    publish(args.input,args.output)
