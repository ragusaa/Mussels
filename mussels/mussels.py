"""
Copyright (C) 2019 Cisco Systems, Inc. and/or its affiliates. All rights reserved.

This module provides the core Mussels class, used by the CLI interface defined in main.py

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from collections import defaultdict
from pathlib import Path

import datetime
import fnmatch
import json
import logging
import os
import platform
import shutil
import sys
import time
from typing import *

if platform.system() == "Windows":
    if not r"c:\program files\git\cmd" in os.environ["PATH"].lower():
        os.environ["PATH"] = os.environ["PATH"] + r";C:\Program Files\Git\cmd"
    if not r"c:\program files\git\mingw64\bin" in os.environ["PATH"].lower():
        os.environ["PATH"] = os.environ["PATH"] + r";C:\Program Files\Git\mingw64\bin"
    if not r"c:\program files\git\usr\bin" in os.environ["PATH"].lower():
        os.environ["PATH"] = os.environ["PATH"] + r";C:\Program Files\Git\usr\bin"
    if not r"c:\program files\git\bin" in os.environ["PATH"].lower():
        os.environ["PATH"] = os.environ["PATH"] + r";C:\Program Files\Git\bin"
import git

import mussels.bookshelf
from mussels.utils import read
from mussels.utils.versions import (
    NVC,
    sort_cookbook_by_version,
    sort_all_recipes_by_version,
    get_item_version,
    platform_is,
    platform_matches,
    pick_platform,
)


class Mussels:
    r"""
      __    __     __  __     ______     ______     ______     __         ______
     /\ "-./  \   /\ \/\ \   /\  ___\   /\  ___\   /\  ___\   /\ \       /\  ___\
     \ \ \-./\ \  \ \ \_\ \  \ \___  \  \ \___  \  \ \  __\   \ \ \____  \ \___  \
      \ \_\ \ \_\  \ \_____\  \/\_____\  \/\_____\  \ \_____\  \ \_____\  \/\_____\
       \/_/  \/_/   \/_____/   \/_____/   \/_____/   \/_____/   \/_____/   \/_____/
    """
    config: dict = {}
    cookbooks: defaultdict = defaultdict(dict)

    recipes: defaultdict = defaultdict(dict)
    sorted_recipes: defaultdict = defaultdict(list)

    tools: defaultdict = defaultdict(dict)
    sorted_tools: defaultdict = defaultdict(list)

    def __init__(
        self,
        data_dir: str = os.path.join(str(Path.home()), ".mussels"),
        log_file: str = os.path.join(
            str(Path.home()), ".mussels", "logs", "mussels.log"
        ),
        log_level: str = "DEBUG",
    ) -> None:
        """
        Mussels class.

        Args:
            data_dir:   path where ClamAV should be installed.
            log_file:   path output log.
            log_level:  log level ("DEBUG", "INFO", "WARNING", "ERROR").
        """
        self.log_file = log_file
        self._init_logging(log_level)

        self.app_data_dir = data_dir

        self._load_config("config.json", self.config)
        self._load_config("cookbooks.json", self.cookbooks)
        self._load_recipes()

    def _init_logging(self, level="DEBUG"):
        """
        Initializes the logging parameters

        Returns:    nothing
        """
        levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARN": logging.WARNING,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }

        self.logger = logging.getLogger("mussels.Mussels")
        self.logger.setLevel(levels[level])

        formatter = logging.Formatter(
            fmt="%(asctime)s - %(levelname)s:  %(message)s",
            datefmt="%m/%d/%Y %I:%M:%S %p",
        )

        if not os.path.exists(os.path.split(self.log_file)[0]):
            os.makedirs(os.path.split(self.log_file)[0])
        filehandler = logging.FileHandler(filename=self.log_file)
        filehandler.setLevel(levels[level])
        filehandler.setFormatter(formatter)

        self.logger.addHandler(filehandler)

    def _load_config(self, filename, config) -> bool:
        """
        Load the cache.
        """
        # load config, if exists.
        try:
            with open(
                os.path.join(self.app_data_dir, "config", filename), "r"
            ) as config_file:
                config.update(json.load(config_file))
        except Exception:
            # No existing config to load, that's probaby ok, but return false to indicate the failure.
            return False

        return True

    def _store_config(self, filename, config) -> bool:
        """
        Update the cache.
        """
        try:
            if not os.path.isdir(os.path.join(self.app_data_dir, "config")):
                os.makedirs(os.path.join(self.app_data_dir, "config"))
        except Exception as exc:
            self.logger.warning(f"Failed to create config directory.  Exception: {exc}")
            return False

        try:
            with open(
                os.path.join(self.app_data_dir, "config", filename), "w"
            ) as config_file:
                json.dump(config, config_file, indent=4)
        except Exception as exc:
            self.logger.warning(f"Failed to update config.  Exception: {exc}")
            return False

        return True

    def _read_cookbook(self, cookbook: str, cookbook_path: str) -> bool:
        """
        Load the recipes and tools from a single cookbook.
        """
        sorted_recipes: defaultdict = defaultdict(list)
        sorted_tools: defaultdict = defaultdict(list)

        # Load the recipes
        recipes = read.recipes(os.path.join(cookbook_path))
        sorted_recipes = sort_cookbook_by_version(recipes)

        self.cookbooks[cookbook]["recipes"] = sorted_recipes
        for recipe in recipes.keys():
            for version in recipes[recipe]:
                if version not in self.recipes[recipe].keys():
                    self.recipes[recipe][version] = {}
                self.recipes[recipe][version][cookbook] = recipes[recipe][version]

        # Load the tools
        tools = read.tools(os.path.join(cookbook_path))
        sorted_tools = sort_cookbook_by_version(tools)

        self.cookbooks[cookbook]["tools"] = sorted_tools
        for tool in tools.keys():
            for version in tools[tool]:
                if version not in self.tools[tool].keys():
                    self.tools[tool][version] = {}
                self.tools[tool][version][cookbook] = tools[tool][version]

        if len(recipes) == 0 and len(tools) == 0:
            return False

        return True

    def _read_bookshelf(self) -> bool:
        """
        Load the recipes and tools from cookbooks in ~/.mussels/cookbooks
        """
        bookshelf = os.path.join(self.app_data_dir, "cookbooks")
        if os.path.isdir(bookshelf):
            for cookbook in os.listdir(bookshelf):
                cookbook_path = os.path.join(
                    os.path.join(self.app_data_dir, "cookbooks"), cookbook
                )
                if os.path.isdir(cookbook_path):
                    if not self._read_cookbook(cookbook, cookbook_path):
                        self.logger.warning(
                            f"Failed to read any recipes or tools from cookbook: {cookbook}"
                        )

            self._store_config("cookbooks.json", self.cookbooks)

        return True

    def _read_local_recipes(self) -> bool:
        """
        Load the recipes and tools from local "mussels" directory
        """
        # Load recipes and tools from `cwd`/mussels directory, if any exist.
        local_recipes = os.path.join(os.getcwd(), "mussels")
        if os.path.isdir(local_recipes):
            if not self._read_cookbook("local", local_recipes):
                return False

            self.cookbooks["local"]["url"] = ""
            self.cookbooks["local"]["path"] = local_recipes
            self.cookbooks["local"]["trusted"] = True

        return True

    def _load_recipes(self) -> bool:
        """
        Load the recipes and tools.
        """
        # If the cache is empty, try reading from the local bookshelf.
        if len(self.recipes) == 0 or len(self.tools) == 0:
            self._read_bookshelf()

        # Load recipes from the local mussels directory, if those exists.
        if not self._read_local_recipes():
            self.logger.warning(
                f"Local `mussels` directory found, but failed to load any recipes or tools."
            )

        self.sorted_recipes, self.all_sorted_recipes = sort_all_recipes_by_version(
            self.recipes
        )
        self.sorted_tools, self.all_sorted_tools = sort_all_recipes_by_version(
            self.tools
        )

        if len(self.sorted_recipes) == 0:
            self.logger.warning(
                f"Failed to find any recipes for platform: {platform.system()}."
            )
            self.logger.warning(
                f"Local recipes must be stored under the current working directory."
            )
            self.logger.warning(
                f"To update your local bookshelf of public cookbooks, run `mussels update`."
            )
            return False

        if len(self.sorted_tools) == 0:
            self.logger.warning(
                f"Failed to find any tools for platform: {platform.system()}"
            )
            self.logger.warning(
                f"Local tools must be stored under under the current working directory."
            )
            self.logger.warning(
                f"To update your local bookshelf of public cookbooks, run `mussels update`."
            )
            return False

        return True

    def _build_recipe(
        self,
        recipe: str,
        version: str,
        cookbook: str,
        platform: str,
        target: str,
        toolchain: dict,
        clean: bool = False,
    ) -> dict:
        """
        Build a specific recipe.

        Args:
            recipe:     The recipe name with no version information.
            version:    The recipe version.

        Returns:    A dictionary of build results
        """
        result = {"name": recipe, "version": version, "success": False}

        if not self.cookbooks[cookbook]["trusted"]:
            self.logger.error(
                f"Unable to build {recipe}={version} from '{cookbook}'. You have not elected to trust '{cookbook}'"
            )
            self.logger.error(
                f"Building recipes involve downloading and executing code from the internet, which carries some risk."
            )
            self.logger.error(
                f"Please review the recipes provided by '{cookbook}' at: {self.cookbooks[cookbook]['url']}."
            )
            self.logger.error(
                f"If you're comfortable with the level of risk, run the following command to trust all recipes from '{cookbook}':"
            )
            self.logger.error(f"")
            self.logger.error(f"    mussels cookbook trust {cookbook}")
            self.logger.error(f"")
            self.logger.error(
                f"Alternatively, you may consider cloning only the recipe you need for your own cookbook."
            )
            self.logger.error(
                f"This is a safer option, though you are still encouraged to review the recipe before using it."
            )
            self.logger.error(
                f"To clone the recipe {recipe}={version} from '{cookbook}', run the following command:"
            )
            self.logger.error(f"")
            self.logger.error(
                f"    mussels recipe clone {recipe} -v {version} -c {cookbook}"
            )
            return result

        start = time.time()

        self.logger.info(f"Attempting to build {recipe}...")

        if version == "":
            # Use the default (highest) version
            try:
                version = self.sorted_recipes[recipe][0]
            except KeyError:
                self.logger.error(f"FAILED to find recipe: {recipe}!")
                result["time elapsed"] = time.time() - start
                return result

        try:
            recipe_class = self.recipes[recipe][version][cookbook]
        except KeyError:
            self.logger.error(f"FAILED to find recipe: {recipe}-{version}!")
            result["time elapsed"] = time.time() - start
            return result

        recipe_object = recipe_class(
            toolchain=toolchain,
            platform=platform,
            target=target,
            data_dir=self.app_data_dir,
        )

        if not recipe_object._build(clean):
            self.logger.error(f"FAILURE: {recipe}-{version} build failed!\n")
        else:
            self.logger.info(f"Success: {recipe}-{version} build succeeded. :)\n")
            result["success"] = True

        result["time elapsed"] = time.time() - start

        return result

    def _get_recipe_version(self, recipe: str, platform: str, target: str) -> NVC:
        """
        Select recipe version based on version requirements.
        Eliminate recipe versions and sorted tools versions based on
        these requirements, and the required_tools requirements of remaining recipes.

        Args:
            recipe:     A specific recipe string, which may include version information.
            cookbook:   The preferred cookbook to select the recipe from.

        :return: named tuple describing the highest qualified version:
            NVC(
                "name"->str,
                "version"->str,
                "cookbook"->str,
            )
        """
        # Select the recipe
        nvc = get_item_version(recipe, self.sorted_recipes)

        # Use "get_item_version()" to prune the list of sorted_tools based on the required tools for the selected recipe.
        for name in self.sorted_recipes:
            for i, each_ver in enumerate(self.sorted_recipes[name]):
                version = each_ver["version"]
                for cookbook in each_ver["cookbooks"]:
                    recipe_class = self.recipes[name][version][cookbook]

                    for each_platform in recipe_class.platforms:
                        if platform_matches(each_platform, platform):
                            variant = recipe_class.platforms[each_platform]
                            try:
                                build_target = variant[target]
                            except Exception:
                                self.logger.warning(
                                    f"Matching recipe {cookbook}:{name}-{version} does not provide build instructions for the target architecture: {target}"
                                )
                                continue

                            for tool in build_target["required_tools"]:
                                try:
                                    get_item_version(tool, self.sorted_tools)
                                except Exception:
                                    raise Exception(
                                        f'No tool definition "{tool}" found. Required by {cookbook}:{name}-{version}.'
                                    )
                            break
        return nvc

    def _identify_build_recipes(
        self, recipe: str, chain: list, platform: str, target: str
    ) -> list:
        """
        Identify all recipes that must be built given a specific recipe.

        Args:
            recipe:     A specific recipe to build.
            chain:      (in,out) A dependency chain starting from the first
                        recursive call used to identify circular dependencies.
        """
        recipe_nvc = self._get_recipe_version(recipe, platform, target)

        if (len(chain) > 0) and (recipe_nvc.name == chain[0]):
            raise ValueError(f"Circular dependencies found! {chain}")
        chain.append(recipe_nvc.name)

        recipes = []

        recipes.append(recipe)

        platform_options = self.recipes[recipe_nvc.name][recipe_nvc.version][
            recipe_nvc.cookbook
        ].platforms.keys()
        matching_platform = pick_platform(platform, platform_options)
        dependencies = self.recipes[recipe_nvc.name][recipe_nvc.version][
            recipe_nvc.cookbook
        ].platforms[matching_platform][target]["dependencies"]
        for dependency in dependencies:
            if ":" not in dependency:
                # If the cookbook isn't explicitly specified for the dependency,
                # select the recipe from the current cookbook.
                dependency = f"{recipe_nvc.cookbook}:{dependency}"

            recipes += self._identify_build_recipes(dependency, chain, platform, target)

        return recipes

    def _get_build_batches(self, recipe: str, platform: str, target: str) -> list:
        """
        Get list of build batches that can be built concurrently.

        Args:
            recipe:    A recipes string in the format [cookbook:]recipe[==version].
        """
        # Identify all recipes that must be built given list of desired builds.
        all_recipes = set(self._identify_build_recipes(recipe, [], platform, target))

        # Build a map of recipes (name,version) tuples to sets of dependency (name,version,cookbook) tuples
        nvc_to_deps = {}
        for recipe in all_recipes:
            recipe_nvc = self._get_recipe_version(recipe, platform, target)
            platform_options = self.recipes[recipe_nvc.name][recipe_nvc.version][
                recipe_nvc.cookbook
            ].platforms.keys()
            matching_platform = pick_platform(platform, platform_options)
            dependencies = self.recipes[recipe_nvc.name][recipe_nvc.version][
                recipe_nvc.cookbook
            ].platforms[matching_platform][target]["dependencies"]
            nvc_to_deps[recipe_nvc] = set(
                [
                    self._get_recipe_version(dependency, platform, target)
                    for dependency in dependencies
                ]
            )

        batches = []

        # While there are dependencies to solve...
        while nvc_to_deps:

            # Get all recipes with no dependencies
            ready = {recipe for recipe, deps in nvc_to_deps.items() if not deps}

            # If there aren't any, we have a loop in the graph
            if not ready:
                msg = "Circular dependencies found!\n"
                msg += json.dumps(nvc_to_deps, indent=4)
                raise ValueError(msg)

            # Remove them from the dependency graph
            for recipe in ready:
                del nvc_to_deps[recipe]
            for deps in nvc_to_deps.values():
                deps.difference_update(ready)

            # Add the batch to the list
            batches.append(ready)

        # Return the list of batches
        return batches

    def build_recipe(
        self,
        recipe: str,
        version: str,
        cookbook: str,
        target: str,
        results: list,
        dry_run: bool = False,
        clean: bool = False,
    ) -> bool:
        """
        Execute a build of a recipe.

        Args:
            recipe:     The recipe to build.
            version:    A specific version to build.  Leave empty ("") to build the newest.
            cookbook:   A specific cookbook to use.  Leave empty ("") if there's probably only one.
            target:     The target architecture to build.
            results:    (out) A list of dictionaries describing the results of the build.
            dry_run:    (optional) Don't actually build, just print the build chain.
        """

        def print_results(results: list):
            """
            Print the build results in a pretty way.

            Args:
                results:    (out) A list of dictionaries describing the results of the build.
            """
            for result in results:
                if result["success"]:
                    self.logger.info(
                        f"Successful build of {result['name']}-{result['version']} completed in {datetime.timedelta(0, result['time elapsed'])}."
                    )
                else:
                    self.logger.error(
                        f"Failure building {result['name']}-{result['version']}, terminated after {datetime.timedelta(0, result['time elapsed'])}"
                    )

        batches: List[dict] = []

        recipe_str = recipe

        if version != "":
            recipe_str = f"{recipe}=={version}"

        if cookbook == "":
            recipe_str = f"local:{recipe_str}"
        else:
            recipe_str = f"{cookbook}:{recipe_str}"

        batches = self._get_build_batches(
            recipe_str, platform=platform.system(), target=target
        )

        #
        # Validate toolchain
        #
        # Collect set of required tools for entire build.
        toolchain = {}
        preferred_tool_versions = set()
        for i, bundle in enumerate(batches):
            for j, recipe_nvc in enumerate(bundle):
                recipe_class = self.recipes[recipe_nvc.name][recipe_nvc.version][
                    recipe_nvc.cookbook
                ]

                for each_platform in recipe_class.platforms:
                    if platform_is(each_platform):
                        for tool in recipe_class.platforms[each_platform][target][
                            "required_tools"
                        ]:
                            tool_nvc = get_item_version(tool, self.sorted_tools)
                            preferred_tool_versions.add(tool_nvc)

        # Check if required tools are installed
        missing_tools = []
        for tool_nvc in preferred_tool_versions:
            tool_found = False
            prefered_tool = self.tools[tool_nvc.name][tool_nvc.version][
                tool_nvc.cookbook
            ](self.app_data_dir)

            if prefered_tool.detect():
                # Preferred tool version is available.
                tool_found = True
                toolchain[tool_nvc.name] = prefered_tool
                if tool_nvc.version != "":
                    self.logger.info(f"    {tool_nvc.name}-{tool_nvc.version} found.")
                else:
                    self.logger.info(f"    {tool_nvc.name} found.")
            else:
                # Check if non-prefered (older, but compatible) version is available.
                if tool_nvc.version != "":
                    self.logger.warning(
                        f"    {tool_nvc.name}-{tool_nvc.version} not found."
                    )
                else:
                    self.logger.warning(f"    {tool_nvc.name} not found.")

                if len(self.sorted_tools[tool_nvc.name]) > 1:
                    self.logger.warning(f"        Checking for alternative versions...")
                    alternative_versions = self.sorted_tools[tool_nvc.name][1:]

                    for alternative_version in alternative_versions:
                        alternative_tool = self.tools[tool_nvc.name][
                            alternative_version["version"]
                        ][alternative_version["cookbooks"][0]](self.app_data_dir)

                        if alternative_tool.detect():
                            # Found a compatible version to use.
                            tool_found = True
                            toolchain[tool_nvc.name] = alternative_tool
                            # Select the version so it will be the default.
                            get_item_version(
                                f"{alternative_version['cookbooks'][0]}:{tool_nvc.name}={alternative_version['version']}",
                                self.sorted_tools,
                            )
                            if alternative_version != "":
                                self.logger.info(
                                    f"    Alternative version {tool_nvc.name}-{alternative_version} found."
                                )
                            else:
                                self.logger.info(
                                    f"    Alternative version {tool_nvc.name} found."
                                )
                        else:
                            if alternative_version != "":
                                self.logger.warning(
                                    f"    Alternative version {tool_nvc.name}-{alternative_version} not found."
                                )
                            else:
                                self.logger.warning(
                                    f"    Alternative version {tool_nvc.name} not found."
                                )

                if not tool_found:
                    # Tool is missing.  Build will fail.
                    missing_tools.append(tool_nvc)

        if len(missing_tools) > 0:
            self.logger.warning("")
            self.logger.warning(
                "The following tools are missing and must be installed for this build to continue:"
            )
            for tool_version in missing_tools:
                if tool_nvc.version != "":
                    self.logger.warning(f"    {tool_nvc.name}-{tool_nvc.version}")
                else:
                    self.logger.warning(f"    {tool_nvc.name}")

            sys.exit(1)

        self.logger.info("Toolchain:")
        for tool in toolchain:
            if toolchain[tool].version != "":
                self.logger.info(f"   {tool}-{toolchain[tool].version}")
            else:
                self.logger.info(f"   {tool}")

        #
        # Perform Build
        #
        if dry_run:
            self.logger.warning("")
            self.logger.warning(r"    ___   ___   _         ___   _     _    ")
            self.logger.warning(r"   | | \ | |_) \ \_/     | |_) | | | | |\ |")
            self.logger.warning(r"   |_|_/ |_| \  |_|      |_| \ \_\_/ |_| \|")
            self.logger.warning("")
            self.logger.info("Build-order of requested recipes:")

        idx = 0
        failure = False
        for i, bundle in enumerate(batches):
            for j, recipe_nvc in enumerate(bundle):
                idx += 1

                platform_options = self.recipes[recipe_nvc.name][recipe_nvc.version][
                    recipe_nvc.cookbook
                ].platforms.keys()
                matching_platform = pick_platform(platform.system(), platform_options)

                if dry_run:
                    self.logger.info(
                        f"   {idx:2} [{i}:{j:2}]: {recipe_nvc.cookbook}:{recipe_nvc.name}-{recipe_nvc.version}"
                    )
                    self.logger.debug(f"      Tool(s):")
                    for tool in self.recipes[recipe_nvc.name][recipe_nvc.version][
                        recipe_nvc.cookbook
                    ].platforms[matching_platform][target]["required_tools"]:
                        tool_nvc = get_item_version(tool, self.sorted_tools)
                        if tool_nvc.version != "":
                            self.logger.debug(
                                f"        {tool_nvc.cookbook}:{tool_nvc.name}-{tool_nvc.version}"
                            )
                        else:
                            self.logger.debug(
                                f"        {tool_nvc.cookbook}:{tool_nvc.name}"
                            )
                    continue

                if failure:
                    self.logger.warning(
                        f"Skipping  {recipe_nvc.cookbook}:{recipe_nvc.name}-{recipe_nvc.version} build due to prior failure."
                    )
                else:
                    result = self._build_recipe(
                        recipe_nvc.name,
                        recipe_nvc.version,
                        recipe_nvc.cookbook,
                        matching_platform,
                        target,
                        toolchain,
                        clean,
                    )
                    results.append(result)
                    if not result["success"]:
                        failure = True

        if not dry_run:
            print_results(results)

        if failure:
            return False
        return True

    def print_recipe_details(
        self, recipe: str, version: dict, verbose: bool, all: bool
    ):
        """
        Print recipe information.
        """
        version_num = version["version"]
        cookbooks = version["cookbooks"]
        self.logger.info(f"    {recipe} v{version_num};  from: {cookbooks}")

        if verbose:
            self.logger.info("")
            for cookbook in cookbooks:
                self.logger.info(f"      Cookbook: {cookbook}")

                book_recipe = self.recipes[recipe][version_num][cookbook]

                if book_recipe.is_collection:
                    self.logger.info(f"        Collection: Yes")
                else:
                    self.logger.info(f"        Collection: No")

                self.logger.info(f"        Platforms:")
                for each_platform in book_recipe.platforms:
                    if all or platform_is(each_platform):
                        self.logger.info(f"          Host platform: {each_platform}")

                        variant = book_recipe.platforms[each_platform]
                        for arch in variant.keys():
                            self.logger.info(f"            Target architecture: {arch}")
                            self.logger.info(
                                f"              Dependencies:      {', '.join(variant[arch]['dependencies'])}"
                            )
                            self.logger.info(
                                f"              Required tools:    {', '.join(variant[arch]['required_tools'])}"
                            )

                        if not all:
                            break
            self.logger.info("")

    def show_recipe(
        self,
        recipe_match: str,
        version_match: str,
        verbose: bool = False,
        all: bool = False,
    ):
        """
        Search recipes for a specific recipe and print recipe details.
        """

        found = False

        if all:
            sorted_recipes = self.all_sorted_recipes
        else:
            sorted_recipes = self.sorted_recipes

        if version_match == "":
            self.logger.info(f'Searching for recipe matching name: "{recipe_match}"...')
        else:
            self.logger.info(
                f'Searching for recipe matching name: "{recipe_match}", version: "{version_match}"...'
            )
        # Attempt to match the recipe name
        for recipe in sorted_recipes:
            if fnmatch.fnmatch(recipe, recipe_match):
                if version_match == "":
                    found = True

                    # Show info for every version
                    for version in sorted_recipes[recipe]:
                        self.print_recipe_details(recipe, version, verbose, all)
                    break
                else:
                    # Attempt to match the version too
                    for version in sorted_recipes[recipe]:
                        if fnmatch.fnmatch(version, version_match):
                            found = True

                            self.print_recipe_details(recipe, version, verbose, all)
                            break
                    if found:
                        break
        if not found:
            if version_match == "":
                self.logger.warning(f'No recipe matching name: "{recipe_match}"')
            else:
                self.logger.warning(
                    f'No recipe matching name: "{recipe_match}", version: "{version_match}"'
                )

    def clone_recipe(self, recipe: str, version: str, cookbook: str, destination: str):
        """
        Search recipes for a specific recipe and copy the file to the CWD.
        """

        def get_cookbook(recipe: str, recipe_version: dict) -> str:
            """
            Return the cookbook name, if only one cookbook provides the recipe-version.
            If more then one cookbook provides the recipe-version, explain the options and return an empty string.
            """
            cookbook = ""

            num_cookbooks = len(recipe_version["cookbooks"])
            if num_cookbooks == 0:
                self.logger.error(
                    f"Recipe {recipe}:{version} not provided by any cookbook!(?!)"
                )

            elif num_cookbooks == 1:
                cookbook = recipe_version["cookbooks"][0]

            else:
                self.logger.error(
                    f'Clone failed: No cookbook specified, and multiple cookbooks provide recipe "{recipe}={recipe_version["version"]}".'
                )
                self.logger.error(
                    f"Please retry with a specific cookbook using the `-c` or `--cookbook` option:"
                )
                self.logger.info(f"")

                self.print_recipe_details(
                    recipe, recipe_version, verbose=True, all=True
                )

            return cookbook

        found = False

        if version == "":
            if cookbook == "":
                self.logger.info(f'Attempting to clone recipe: "{recipe}"...')
            else:
                self.logger.info(
                    f'Attempting to clone recipe: "{cookbook}: {recipe}"...'
                )
        else:
            if cookbook == "":
                self.logger.info(f'Attempting to clone recipe: "{recipe}={version}"...')
            else:
                self.logger.info(
                    f'Attempting to clone recipe: "{cookbook}:{recipe}={version}"...'
                )

        try:
            recipe_versions = self.sorted_recipes[recipe]
        except KeyError:
            self.logger.error(f'Clone failed: No such recipe "{recipe}"')
            return False

        # Identify highest available version, for future reference.
        highest_recipe_version = recipe_versions[0]

        #
        # Now repeat the above if/else logic to select the exact recipe requested.
        #

        if version == "":
            if cookbook == "":
                # neither version nor cookbook was specified.
                self.logger.info(
                    f"No version or cookbook specified, will select highest available version."
                )
                version = highest_recipe_version["version"]

                cookbook = get_cookbook(version, highest_recipe_version)

                if cookbook == "":
                    return False

            else:
                # cookbook specified, but version wasn't.
                self.logger.info(
                    f'No version specified, will select highest version provided by cookbook: "{cookbook}".'
                )

                selected_recipe_version = {}

                for recipe_version in recipe_versions:
                    if cookbook in recipe_version["cookbooks"]:
                        selected_recipe_version = recipe_version
                        break

                if selected_recipe_version == {}:
                    self.logger.error(
                        f'Clone failed: Requested recipe "{recipe}" could not be found in cookbook: "{cookbook}".'
                    )
                    return False

                version = selected_recipe_version["version"]

                if (
                    selected_recipe_version["version"]
                    != highest_recipe_version["version"]
                ):
                    self.logger.warning(
                        f'The version selected from cookbook "{cookbook}" is not the highest version available.'
                    )
                    self.logger.warning(
                        f"A newer version appears to be available from other sources:"
                    )
                    self.logger.info(f"")
                    self.print_recipe_details(
                        recipe, highest_recipe_version, verbose=True, all=True
                    )

        else:
            # version specified
            if cookbook == "":
                self.logger.info(
                    f"No cookbook specified, will select recipe only if version is provided by only one cookbook."
                )

                selected_recipe_version = {}

                for recipe_version in recipe_versions:
                    if version == recipe_version["version"]:

                        cookbook = get_cookbook(recipe, recipe_version)
                        break

                if cookbook == "":
                    return False

            else:
                # version and cookbook specified.
                pass

        if destination == "":
            destination = os.getcwd()

        try:
            recipe_class = self.recipes[recipe][version][cookbook]
        except KeyError:
            self.logger.error(
                f'Clone failed: Requested recipe "{cookbook}: {recipe} = {version}" could not be found.'
            )
            return False

        recipe_object = recipe_class(toolchain={}, data_dir=self.app_data_dir)

        clone_path = recipe_object._clone(destination=destination)
        if clone_path == "":
            return False

        self.logger.info(
            f'Successfully cloned recipe "{cookbook}:{recipe}={version}" to:'
        )
        self.logger.info(f"    {clone_path}")

        return True

    def list_recipes(self, verbose: bool = False, all: bool = False):
        """
        Print out a list of all recipes and all collections.
        """
        has_collections = False

        if all:
            sorted_recipes = self.all_sorted_recipes
        else:
            sorted_recipes = self.sorted_recipes

        self.logger.info("Recipes:")
        for recipe in sorted_recipes:
            newest_version = sorted_recipes[recipe][0]["version"]
            cookbooks = list(self.recipes[recipe][newest_version].keys())
            if not self.recipes[recipe][newest_version][cookbooks[0]].is_collection:
                if not verbose:
                    outline = f"    {recipe:10} "
                    for i, version in enumerate(sorted_recipes[recipe]):
                        if i == 0:
                            outline += f" {version['version']}*"
                        else:
                            outline += f", {version['version']}"
                    outline += ""
                    self.logger.info(outline)
                else:
                    outline = f"    {recipe:10} "
                    for i, version in enumerate(sorted_recipes[recipe]):
                        if i == 0:
                            outline += f" {version['version']} {version['cookbooks']}*"
                        else:
                            outline += f", {version['version']} {version['cookbooks']}"
                    outline += ""
                    self.logger.info(outline)

        for recipe in sorted_recipes:
            newest_version = sorted_recipes[recipe][0]["version"]
            cookbooks = list(self.recipes[recipe][newest_version].keys())
            if self.recipes[recipe][newest_version][cookbooks[0]].is_collection:
                if not has_collections:
                    self.logger.info("")
                    self.logger.info("Collections:")
                    has_collections = True

                if not verbose:
                    outline = f"    {recipe:10} "
                    for i, version in enumerate(sorted_recipes[recipe]):
                        if i == 0:
                            outline += f" {version['version']}*"
                        else:
                            outline += f", {version['version']}"
                    outline += ""
                    self.logger.info(outline)
                else:
                    outline = f"    {recipe:10} "
                    for i, version in enumerate(sorted_recipes[recipe]):
                        if i == 0:
                            outline += f" {version['version']} {version['cookbooks']}*"
                        else:
                            outline += f", {version['version']} {version['cookbooks']}"
                    outline += ""
                    self.logger.info(outline)

    def update_cookbooks(self) -> None:
        """
        Attempt to update each cookbook in using Git to clone or pull each repo.
        If git isn't available, warn the user they should probably install Git and add it to their PATH.
        """
        # Create ~/.mussels/bookshelf if it doesn't already exist.
        os.makedirs(os.path.join(self.app_data_dir, "cookbooks"), exist_ok=True)

        # Get url for each cookbook from the mussels bookshelf.
        for book in mussels.bookshelf.cookbooks:
            repo_dir = os.path.join(self.app_data_dir, "cookbooks", book)
            self.cookbooks[book]["path"] = repo_dir
            self.cookbooks[book]["url"] = mussels.bookshelf.cookbooks[book]["url"]
            if "trusted" not in self.cookbooks[book]:
                self.cookbooks[book]["trusted"] = False

        for book in self.cookbooks:
            repo_dir = os.path.join(self.app_data_dir, "cookbooks", book)

            if self.cookbooks[book]["url"] != "":
                if not os.path.isdir(repo_dir):
                    repo = git.Repo.clone_from(self.cookbooks[book]["url"], repo_dir)
                else:
                    repo = git.Repo(repo_dir)
                    repo.git.pull()

            self._read_cookbook(book, repo_dir)

        self._store_config("cookbooks.json", self.cookbooks)

    def list_cookbooks(self, verbose: bool = False):
        """
        Print out a list of all cookbooks.
        """

        self.logger.info("Cookbooks:")
        for cookbook in self.cookbooks:
            self.logger.info(f"    {cookbook}")

            if verbose:
                if cookbook == "local":
                    self.logger.info(f"        url:     n/a")
                else:
                    self.logger.info(
                        f"        url:     {self.cookbooks[cookbook]['url']}"
                    )
                self.logger.info(f"        path:    {self.cookbooks[cookbook]['path']}")
                self.logger.info(
                    f"        trusted: {self.cookbooks[cookbook]['trusted']}"
                )
                self.logger.info(f"")

    def show_cookbook(self, cookbook_match: str, verbose: bool):
        """
        Search cookbooks for a specific cookbook and print the details.
        """
        found = False

        self.logger.info(f'Searching for cookbook matching name: "{cookbook_match}"...')

        # Attempt to match the cookbook name
        for cookbook in self.cookbooks:
            if fnmatch.fnmatch(cookbook, cookbook_match):
                found = True

                self.logger.info(f"    {cookbook}")
                if cookbook == "local":
                    self.logger.info(f"        url:     n/a")
                else:
                    self.logger.info(
                        f"        url:     {self.cookbooks[cookbook]['url']}"
                    )
                self.logger.info(f"        path:    {self.cookbooks[cookbook]['path']}")
                self.logger.info(
                    f"        trusted: {self.cookbooks[cookbook]['trusted']}"
                )

                if verbose:
                    self.logger.info(f"")
                    if len(self.cookbooks[cookbook]["recipes"].keys()) > 0:
                        self.logger.info(f"    Recipes:")
                        for recipe in self.cookbooks[cookbook]["recipes"]:
                            self.logger.info(
                                f"        {recipe} : {self.cookbooks[cookbook]['recipes'][recipe]}"
                            )
                        self.logger.info(f"")
                    if len(self.cookbooks[cookbook]["tools"].keys()) > 0:
                        self.logger.info(f"    Tools:")
                        for tool in self.cookbooks[cookbook]["tools"]:
                            self.logger.info(
                                f"        {tool} : {self.cookbooks[cookbook]['tools'][tool]}"
                            )

        if not found:
            self.logger.warning(f'No cookbook matching name: "{cookbook_match}"')

    def clean_cache(self):
        """
        Clear the cache files.
        """
        self.logger.info(
            f"Clearing cache directory ( {os.path.join(self.app_data_dir, 'cache')} )..."
        )

        if os.path.exists(os.path.join(self.app_data_dir, "cache")):
            shutil.rmtree(os.path.join(self.app_data_dir, "cache"))
            self.logger.info(f"Cache directory cleared.")
        else:
            self.logger.info(f"No cache directory to clear.")

    def clean_install(self):
        """
        Clear the install files.
        """
        self.logger.info(
            f"Clearing install directory ( {os.path.join(self.app_data_dir, 'install')} )..."
        )

        if os.path.exists(os.path.join(self.app_data_dir, "install")):
            shutil.rmtree(os.path.join(self.app_data_dir, "install"))
            self.logger.info(f"Install directory cleared.")
        else:
            self.logger.info(f"No install directory to clear.")

    def clean_logs(self):
        """
        Clear the log files.
        """
        self.logger.info(
            f"Clearing logs directory ( {os.path.join(self.app_data_dir, 'logs')} )..."
        )

        if os.path.exists(os.path.join(self.app_data_dir, "logs")):
            shutil.rmtree(os.path.join(self.app_data_dir, "logs"))
            self.logger.info(f"Logs directory cleared.")
        else:
            self.logger.info(f"No logs directory to clear.")

    def clean_all(self):
        """
        Clear all Mussels files.
        """
        self.logger.info(
            f"Clearing Mussels directory ( {os.path.join(self.app_data_dir)} )..."
        )

        if os.path.exists(os.path.join(self.app_data_dir)):
            shutil.rmtree(os.path.join(self.app_data_dir))
            self.logger.info(f"Mussels directory cleared.")
        else:
            self.logger.info(f"No Mussels directory to clear.")

    def config_trust_cookbook(self, cookbook):
        """
        Update config to indicate that a given cookbook is trusted.
        """
        if cookbook not in self.cookbooks:
            self.logger.error(
                f"Can't trust cookbook '{cookbook}'. Cookbook is unknown."
            )

        self.logger.info(f"'{cookbook}' cookbook is now trusted.")

        self.cookbooks[cookbook]["trusted"] = True

        self._store_config("cookbooks.json", self.cookbooks)

    def config_add_cookbook(self, cookbook, author, url):
        """
        Update config to indicate that a given cookbook is trusted.
        """
        self.cookbooks[cookbook]["author"] = author
        self.cookbooks[cookbook]["url"] = url
        self.cookbooks[cookbook]["trusted"] = True

        self._store_config("cookbooks.json", self.cookbooks)

    def config_remove_cookbook(self, cookbook):
        self.cookbooks.pop(cookbook)

        self._store_config("cookbooks.json", self.cookbooks)
