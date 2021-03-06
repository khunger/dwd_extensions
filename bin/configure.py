#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2015 Ernst Basler + Partner AG (EBP).
# All Rights Reserved.
# http://www.ebp.ch/
#
# This software is the confidential and proprietary information of Ernst
# Basler + Partner AG ("Confidential Information").  You shall not
# disclose such Confidential Information and shall use it only in
# accordance with the terms of the license agreement you entered into
# with EBP.
#
# EBP MAKES NO REPRESENTATIONS OR WARRANTIES ABOUT THE SUITABILITY OF
# THE SOFTWARE, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE, OR NON-INFRINGEMENT. EBP SHALL NOT BE LIABLE FOR ANY DAMAGES
# SUFFERED BY LICENSEE AS A RESULT OF USING, MODIFYING OR DISTRIBUTING
# THIS SOFTWARE OR ITS DERIVATIVES.

import os
import signal
import sys
import argparse
import ConfigParser
import textwrap
import traceback
from xml.etree.ElementTree import ElementTree


def print_info():
    """Prints the description of this script.
    """
    print textwrap.dedent("""\
    *********************************************************************
    * Call this script to prepare the paths required in the config files
    * of the pytroll package.
    *
    * It reads the key files coming with this package.
    * It asks for a value to each key interactively
    * (an empty value will leave the old one as it is).
    * It writes the key values to the key file.
    * It sets the values in the related config files.
    *
    * arguments:
    * -p, --path <path to config files>
    *
    *********************************************************************
    """)


def _get_config_file(configPath, keyFileName):
    """Returns for a given key file the full path to the related config file.

    If there exist a config file for the given key file
    in the specified path then the full path to the config file
    will be returned; otherwise None.
    """
    configBaseName = os.path.splitext(keyFileName)[0]
    for folder, subs, files in os.walk(configPath):
        if configBaseName in files:
            return os.path.join(folder, configBaseName)
    return None


def _ask_user(section, name, value):
    """Returns user input if there was one; otherwise the given old value.
    """
    if sys.version_info[0] > 2:
        userValue = input("".join(["Please enter [", section, "] -> ",
                                   name, " (", value, "): "]))
    else:
        userValue = raw_input("".join(["Please enter [", section, "] -> ",
                                       name, " (", value, "): "]))
    # missing user input means leave the old value as it is
    if userValue:
        return userValue
    else:
        return value


def set_text_by_attribute(elem, attr_name, attr_value, new_text):
    if attr_name in elem.attrib and elem.attrib[attr_name] == attr_value:
        elem.text = new_text
        print "setting value of node with %s = %s to %s" % (attr_name,
                                                            attr_value,
                                                            new_text)
    for ch in elem:
        set_text_by_attribute(ch, attr_name, attr_value, new_text)


def set_xml_values(keyParser, configFileName, non_interactive):
    """Sets the key values of keyParser in given xml config file.
    """
    tree = ElementTree()
    treeElement = tree.parse(configFileName)
    # iterate over key file where section and option equals the tag name
    for section in keyParser.sections():
        items = keyParser.items(section)
        for name, value in items:
            if non_interactive is True:
                userValue = value
            else:
                userValue = _ask_user(section, name, value)
            keyParser.set(section, name, userValue)
            set_text_by_attribute(treeElement, "id", name, userValue)
    tree.write(configFileName, encoding="utf-8")


def main():
    """Sets the key values in the corresponding config files.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--path", dest="config_path", type=str,
                        default='',
                        help="put in the path to config files")
    parser.add_argument("-ni", "--non-interactive", dest="non_interactive",
                        action='store_const', const=True, default=False,
                        help="no user interaction, use default values")

    if len(sys.argv) <= 1:
        print_info()
        sys.exit()
    else:
        args = parser.parse_args()

    configPath = args.config_path
    if configPath == '':
        print_info()
        sys.exit()

    keyPath = os.path.join(configPath, "keys")

    for folder, subs, files in os.walk(keyPath):
        for f in files:
            try:
                # open and parse key file
                keyFileName = os.path.join(folder, f)
                keyParser = ConfigParser.ConfigParser()
                keyParser.read(keyFileName)
                keyFile = open(keyFileName, "w")

                # open and parse related config file
                configFileName = _get_config_file(configPath, f)
                hasFound = configFileName is not None
                if not hasFound:
                    print " ".join(["MISSING CONFIG FILE IN PATH",
                                    configPath,
                                    "FOR THE GIVEN KEY FILE", f])
                    print "PLEASE CHECK THE MAPPING OF THE CONFIG FILES "\
                        "TO THEIR CORRESPONDING KEY FILES\n\n"
                    continue
                confParser = ConfigParser.ConfigParser()
                confParser.read(configFileName)
                configFile = open(configFileName, "w")

                print "".join(["reading files [", keyFileName, ", ",
                               configFileName, "]"])
                for section in keyParser.sections():
                    items = keyParser.items(section)
                    for name, value in items:
                        if args.non_interactive is True:
                            userValue = value
                        else:
                            userValue = _ask_user(section, name, value)
                        keyParser.set(section, name, userValue)
                        try:
                            confParser.set(section, name, userValue)
                        except ConfigParser.NoSectionError:
                            print "".join(["\n", "MISSING SECTION [",
                                           section, "] IN THE CONFIG FILE ",
                                           configFileName])
                            print "PLEASE CHECK THE MAPPING OF THE CONFIG "\
                                "FILES TO THEIR CORRESPONDING KEY FILES\n\n"
            except ConfigParser.MissingSectionHeaderError:
                if configFileName.endswith("xml"):
                    print "".join(["reading files [", keyFileName, ", ",
                                   configFileName, "]"])
                    set_xml_values(keyParser, configFileName,
                                   args.non_interactive)
                    keyParser.write(keyFile)
                hasFound = False
            except Exception, ex:
                print traceback.format_exc()
            finally:
                if hasFound:
                    keyParser.write(keyFile)
                    confParser.write(configFile)
                    configFile.close()
                keyFile.close()
                print "written and closed"


if __name__ == "__main__":
    main()
    # workaround to terminate python interpreter in interactive mode
    pid = os.getpid()
    os.kill(pid, signal.SIGTERM)
