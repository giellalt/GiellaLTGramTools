# -*- coding:utf-8 -*-

# Copyright © 2020-2024 UiT The Arctic University of Norway
# License: GPL3  # noqa: ERA001
# Author: Børre Gaup <borre.gaup@uit.no>
"""Check if grammarchecker tests pass."""

import io
import sys
from pathlib import Path

import yaml
from corpustools import errormarkup  # type: ignore
from lxml import etree

from giellaltgram.gramcheck_comparator import (
    COLORS,
    UI,
    GramChecker,
    GramTest,
    get_pipespecs,
)


class YamlGramChecker(GramChecker):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.checker = self.app()

    @staticmethod
    def print_error(string):
        print(string, file=sys.stderr)

    def get_variant(self, spec_file: Path):
        (default_pipe, available_variants) = get_pipespecs(spec_file)

        if self.config.get("variants") is None:
            return f"--variant {default_pipe}"

        variants = {
            variant.replace("-dev", "") if spec_file.suffix == ".zhfst" else variant
            for variant in self.config.get("variants")
        }
        for variant in variants:
            if variant in available_variants:
                return f"--variant {variant}"

        self.print_error(
            "Error in section Variant of the yaml file.\n"
            "There is no pipeline named "
            f"{variant} in {spec_file}"
        )
        available_names = "\n".join(available_variants)
        self.print_error("Available pipelines are\n" f"{available_names}")

        raise SystemExit(5)

    def app(self):
        spec_file = self.config.get("spec")

        checker_spec = (
            f"--archive {spec_file}"
            if spec_file.suffix == ".zcheck"
            else f"--spec {spec_file}"
        )

        return f"divvun-checker {checker_spec} {self.get_variant(spec_file)}"


class YamlGramTest(GramTest):
    explanations = {
        "tp": "GramDivvun found marked up error and has the suggested correction",
        "fp1": "GramDivvun found manually marked up error, but corrected wrongly",
        "fp2": "GramDivvun found error which is not manually marked up",
        "fn1": "GramDivvun found manually marked up error, but has no correction",
        "fn2": "GramDivvun did not find manually marked up error",
    }

    def __init__(self, args):
        super().__init__()
        self.config = self.load_config(args)

    def load_config(self, args):
        config = {}

        if args.silent:
            config["out"] = GramTest.NoOutput(args)
        else:
            config["out"] = {
                "normal": GramTest.NormalOutput,
                "terse": GramTest.TerseOutput,
                "compact": GramTest.CompactOutput,
                "silent": GramTest.NoOutput,
                "final": GramTest.FinalOutput,
            }.get(args.output, lambda x: None)(args)

        config["test_file"] = Path(args.test_files[0])

        if not args.colour:
            for key in list(COLORS.keys()):
                COLORS[key] = ""

        yaml_settings = self.yaml_reader(config["test_file"])

        config["spec"] = (
            config["test_file"].parent / yaml_settings.get("Config").get("Spec")
            if not args.spec
            else Path(args.spec)
        )
        config["variants"] = (
            yaml_settings.get("Config").get("Variants")
            if not args.variant
            else [args.variant]
        )
        config["tests"] = yaml_settings.get("Tests", [])

        if args.total and len(args.test_files) == 1:
            notfixed = (
                config["test_file"].parent / f"{config['test_file'].stem}.notfixed.yaml"
            )
            tests = self.yaml_reader(notfixed).get("Tests")
            if notfixed.is_file() and tests:
                config["tests"].extend(tests)

        if len(args.test_files) > 1:
            for test_file in args.test_files[1:]:
                tests = self.yaml_reader(Path(test_file)).get("Tests")
                if tests:
                    config["tests"].extend(tests)

        return config

    @staticmethod
    def yaml_reader(test_file):
        with test_file.open() as test_file:
            return yaml.load(test_file, Loader=yaml.FullLoader)

    def make_error_markup(self, text):
        para = etree.Element("p")
        try:
            para.text = text
            errormarkup.convert_to_errormarkupxml(para)
        except TypeError:
            print(f'Error in {self.config["test_file"]}')
            print(text, "is not a string")
        return para

    @property
    def paragraphs(self):
        grammarchecker = YamlGramChecker(self.config)

        return (
            (
                grammarchecker.get_data(
                    str(self.config["test_file"]), self.make_error_markup(text)
                )
                for text in self.config["tests"]
            )
            if self.config["tests"]
            else []
        )

    def move_passes_from_fail(self):
        if "FAIL" in self.config["test_file"].name and any(self.test_results):
            passing_tests = [
                self.config["tests"][index]
                for (index, test_result) in enumerate(self.test_results)
                if test_result
            ]

            pass_path = Path(str(self.config["test_file"]).replace("FAIL", "PASS"))
            with pass_path.open("a") as pass_stream:
                print(
                    "\n".join([f'  - "{this_test}"' for this_test in passing_tests]),
                    file=pass_stream,
                )

            with io.StringIO() as temp_stream:
                with self.config["test_file"].open("r") as _input:
                    temp_stream.write(
                        "".join(
                            [
                                line
                                for line in _input
                                if not any(
                                    passing_test in line.strip()
                                    for passing_test in passing_tests
                                )
                            ]
                        )
                    )
                self.config["test_file"].open("w").write(temp_stream.getvalue())

    def run(self):
        failed_or_not = super().run()

        self.move_passes_from_fail()

        return failed_or_not


class YamlUI(UI):
    def __init__(self):
        super().__init__()

        self.description = "Test errormarkuped up sentences"
        self.add_argument(
            "-o",
            "--output",
            choices=["normal", "compact", "terse", "final"],
            dest="output",
            default="normal",
            help="""Desired output style (Default: normal)""",
        )
        self.add_argument(
            "-q",
            "--silent",
            dest="silent",
            action="store_true",
            help="Hide all output; exit code only",
        )
        self.add_argument(
            "-p",
            "--hide-passes",
            dest="hide_pass",
            action="store_true",
            help="Suppresses passes to make finding fails easier",
        )
        self.add_argument(
            "-s",
            "--spec",
            dest="spec",
            required=False,
            help="""Path to the pipeline.xml spec file. Usefull when doing out
            of tree builds""",
        )
        self.add_argument(
            "-V",
            "--variant",
            dest="variant",
            required=False,
            help="""Which variant should be used.""",
        )
        self.add_argument(
            "-t",
            "--total",
            dest="total",
            action="store_true",
            required=False,
            help="""Merge tests from x.yaml and x.notfixed.yaml""",
        )
        self.add_argument(
            "-v",
            "--verbose",
            dest="verbose",
            action="store_true",
            help="More verbose output.",
        )
        self.add_argument("test_files", nargs="+", help="YAML files with test rules")

        self.test = YamlGramTest(self.parse_args())


def main():
    try:
        ui = YamlUI()
        ui.start()
    except KeyboardInterrupt:
        sys.exit(130)
