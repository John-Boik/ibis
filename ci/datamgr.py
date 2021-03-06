#!/usr/bin/env python

import os
import getpass
import tempfile
import tarfile
import operator

import sqlalchemy as sa

import numpy as np
import pandas as pd

import click

try:
    import sh
except ImportError:
    import pbs as sh


@click.group()
def cli():
    pass


@cli.command()
@click.argument('tables', nargs=-1)
@click.option('-S', '--script', type=click.File('rt'), required=True)
@click.option(
    '-d', '--database',
    default=os.environ.get(
        'IBIS_TEST_POSTGRES_DB', os.environ.get('PGDATABASE', 'ibis_testing')
    ),
)
@click.option(
    '-D', '--data-directory',
    default=tempfile.gettempdir(), type=click.Path(exists=True)
)
def postgres(script, tables, database, data_directory):
    username = os.environ.get(
        'IBIS_POSTGRES_USER', os.environ.get('PGUSER', getpass.getuser())
    )
    host = os.environ.get('PGHOST', 'localhost')
    password = os.environ.get('IBIS_POSTGRES_PASS', os.environ.get('PGPASS'))
    url = sa.engine.url.URL(
        'postgresql',
        username=username,
        host=host,
        password=password,
    )
    engine = sa.create_engine(str(url), isolation_level='AUTOCOMMIT')
    engine.execute('DROP DATABASE IF EXISTS "{}"'.format(database))
    engine.execute('CREATE DATABASE "{}"'.format(database))

    url = sa.engine.url.URL(
        'postgresql',
        username=username,
        host=host,
        password=password,
        database=database,
    )
    engine = sa.create_engine(str(url))
    script_text = script.read()
    with engine.begin() as con:
        con.execute(script_text)

    table_paths = [
        os.path.join(data_directory, '{}.csv'.format(table))
        for table in tables
    ]
    dtype = {'bool_col': np.bool_}
    for table, path in zip(tables, table_paths):
        df = pd.read_csv(path, index_col=None, header=0, dtype=dtype)
        df.to_sql(table, engine, index=False, if_exists='append')
    engine = sa.create_engine(str(url), isolation_level='AUTOCOMMIT')
    engine.execute('VACUUM FULL ANALYZE')


@cli.command()
@click.argument('tables', nargs=-1)
@click.option('-S', '--script', type=click.File('rt'), required=True)
@click.option(
    '-d', '--database',
    default=os.environ.get('IBIS_TEST_SQLITE_DB_PATH', 'ibis_testing.db')
)
@click.option(
    '-D', '--data-directory',
    default=tempfile.gettempdir(), type=click.Path(exists=True)
)
def sqlite(script, tables, database, data_directory):
    database = os.path.abspath(database)
    if os.path.exists(database):
        try:
            os.remove(database)
        except OSError:
            pass
    engine = sa.create_engine('sqlite:///{}'.format(database))
    script_text = script.read()
    with engine.begin() as con:
        con.connection.connection.executescript(script_text)
    table_paths = [
        os.path.join(data_directory, '{}.csv'.format(table))
        for table in tables
    ]
    for table, path in zip(tables, table_paths):
        df = pd.read_csv(path, index_col=None, header=0)
        with engine.begin() as con:
            df.to_sql(table, con, index=False, if_exists='append')
    engine.execute('VACUUM')
    engine.execute('VACUUM ANALYZE')


if os.environ.get('APPVEYOR', None) is not None:
    curl = sh.Command('C:\\Tools\\curl\\bin\\curl.exe')
else:
    curl = sh.curl


@cli.command()
@click.argument(
    'base_url',
    required=False,
    default='https://storage.googleapis.com/ibis-ci-data'  # noqa: E501
)
@click.option('-d', '--data', multiple=True)
@click.option('-D', '--directory', default='.', type=click.Path(exists=False))
def download(base_url, data, directory):
    if not data:
        data = 'ibis-testing-data.tar.gz',

    if not os.path.exists(directory):
        os.mkdir(directory)

    for piece in data:
        data_url = '{}/{}'.format(base_url, piece)
        path = os.path.join(directory, piece)

        curl(
            data_url, o=path, L=True,
            _out=click.get_binary_stream('stdout'),
            _err=click.get_binary_stream('stderr'),
        )

        if piece.endswith(('.tar', '.gz', '.bz2', '.xz')):
            with tarfile.open(path, mode='r|gz') as f:
                f.extractall(path=directory)


def parse_env(ctx, param, values):
    pairs = []
    for envar in values:
        try:
            name, value = envar.split('=', 1)
        except ValueError:
            raise click.ClickException(
                'Environment variables must be of the form NAME=VALUE. '
                '{} is not in this format'.format(envar)
            )
        pairs.append((name, value))
    return dict(pairs)


@cli.command()
@click.argument('data_directory', type=click.Path(exists=True))
@click.option('-e', '--environment', multiple=True, callback=parse_env)
def env(data_directory, environment):
    envars = dict([
        ('IBIS_TEST_IMPALA_HOST', 'impala'),
        ('IBIS_TEST_NN_HOST', 'impala'),
        ('IBIS_TEST_IMPALA_POST', 21050),
        ('IBIS_TEST_WEBHDFS_PORT', 50070),
        ('IBIS_TEST_WEBHDFS_USER', 'ubuntu'),
        (
            'IBIS_TEST_SQLITE_DB_PATH',
            os.path.join(data_directory, 'ibis_testing.db'),
        ),
        (
            'DIAMONDS_CSV',
            os.path.join(data_directory, 'diamonds.csv')
        ),
        (
            'BATTING_CSV',
            os.path.join(data_directory, 'batting.csv')
        ),
        (
            'AWARDS_PLAYERS_CSV',
            os.path.join(data_directory, 'awards_players.csv')
        ),
        (
            'FUNCTIONAL_ALLTYPES_CSV',
            os.path.join(data_directory, 'functional_alltypes.csv')
        ),
        ('IBIS_TEST_POSTGRES_DB', 'ibis_testing'),
        ('IBIS_POSTGRES_USER', getpass.getuser()),
        ('IBIS_POSTGRES_PASS', ''),
    ])
    envars.update(environment)
    string = '\n'.join(
        '='.join((name, str(value)))
        for name, value in sorted(envars.items(), key=operator.itemgetter(0))
    )
    click.echo(string)


if __name__ == '__main__':
    cli()
