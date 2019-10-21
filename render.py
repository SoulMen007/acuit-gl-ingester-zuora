#!/usr/bin/env python
import argparse

import jinja2
import yaml


def load_template(template_filename):
    with open(template_filename, 'r') as f:
        template_content = f.read()

    return jinja2.Template(template_content)


def load_vars(var_filenames):
    vars = {}
    for filename in var_filenames:
        with open(filename, 'r') as f:
            secrets_content = f.read()
        content = yaml.full_load(secrets_content) or {}
        assert(isinstance(content, dict))
        vars.update(content)

    return vars


def save_output(result, output_filename):
    with open(output_filename, 'w') as f:
        f.write(result)


def render(template_filename, var_filenames):
    template = load_template(template_filename)
    vars = load_vars(var_filenames)

    result = template.render(**vars)

    assert(template_filename.endswith('.template'))
    output_filename = template_filename.replace('.template', '')

    save_output(result, output_filename)


def get_args():
    parser = argparse.ArgumentParser(description='Render a template file with variable injection')

    parser.add_argument(
        dest='template_filename',
        help='Input template'
    )

    parser.add_argument(
        nargs='+',
        dest='var_filenames',
        help='Variable files'
    )

    return parser.parse_args()


if __name__ == '__main__':
    args = get_args()
    render(args.template_filename, args.var_filenames)