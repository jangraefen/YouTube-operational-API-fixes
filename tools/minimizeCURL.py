#!/usr/bin/env python

## /!\ Assume that the content of `curlCommandFilePath` is trusted /!\
# TODO: precising or/and lowering this trust level would be interesting
# Note that this algorithm doesn't currently minimize specifically YouTube requests (like `--data-raw/context/client/clientVersion`), should potentially add in the future useless character removal which would be a more general but incomplete approach.

'''
For the moment this algorithm only removes unnecessary:
- headers
- URL parameters
- cookies
- raw data
'''

import shlex
import subprocess
import json
import copy
import sys
from urllib.parse import urlparse, parse_qs, quote_plus
import re
import os

# Could precise the input file and possibly remove the output one as the minimized requests start to be short.
if len(sys.argv) < 3:
    print('Usage: ./minimizeCURL curlCommand.txt "Wanted output"')
    exit(1)

curlCommandFilePath = sys.argv[1]
wantedOutput = sys.argv[2].encode('utf-8')

# The purpose of these parameters is to reduce requests done when developing this script:
removeHeaders = True
removeUrlParameters = True
removeCookies = True
removeRawData = True

PRINT_TRY_TO_REMOVE = False

VERIFY_INITIAL_COMMAND = True

def printTryToRemove(toRemove):
    if PRINT_TRY_TO_REMOVE:
        print(f'Try to remove: {toRemove}!')

# Pay attention to provide a command giving plaintext output, so might required to remove `Accept-Encoding` HTTPS header.
with open(curlCommandFilePath) as f:
    command = f.read()

def executeCommand(command):
    # `stderr = subprocess.DEVNULL` is used to get rid of curl progress.
    # Could also add `-s` curl argument.
    try:
        result = subprocess.check_output(command, shell = True, stderr = subprocess.DEVNULL)
    except:
        return b''
    return result

def getCommandScript(fileName):
    return f'{fileName}.sh'

def writeCommand(fileName, command):
    with open(getCommandScript(fileName), 'w') as f:
        f.write(command)

PARTIALLY_MINIMIZED_CURL_SCRIPT_NAME = 'partially_minimized_curl'

def isCommandStillFine(command):
    result = executeCommand(command)
    isCommandStillFineResult = wantedOutput in result
    # [Benjamin-Loison/cpython/issues/48](https://github.com/Benjamin-Loison/cpython/issues/48)
    if isCommandStillFineResult:
        writeCommand(PARTIALLY_MINIMIZED_CURL_SCRIPT_NAME, command)
    return isCommandStillFineResult

def getCommandLengthFormatted(command):
    return f'{len(command):,}'

def printThatCommandIsStillFine(command):
    print(f'Command with length {getCommandLengthFormatted(command)} is still fine.')

# For Chromium support:
command = command.replace(' \\\n ', '')

print(f'Initial command length: {getCommandLengthFormatted(command)}.')
# To verify that the user provided the correct `wantedOutput` to keep during the minimization.
if VERIFY_INITIAL_COMMAND and not isCommandStillFine(command):
    print('The wanted output isn\'t contained in the result of the original curl command!')
    exit(1)

if removeHeaders:
    print('Removing headers')

    # Should try to minimize the number of requests done, by testing half of parameters at each request.
    previousArgumentsIndex = 0
    while True:
        changedSomething = False
        arguments = shlex.split(command)
        for argumentsIndex in range(previousArgumentsIndex, len(arguments) - 1):
            argument, nextArgument = arguments[argumentsIndex : argumentsIndex + 2]
            if argument == '-H':
                previousCommand = command
                printTryToRemove(arguments[argumentsIndex : argumentsIndex + 2])
                del arguments[argumentsIndex : argumentsIndex + 2]
                command = shlex.join(arguments)
                if isCommandStillFine(command):
                    printThatCommandIsStillFine(command)
                    previousArgumentsIndex = argumentsIndex
                    changedSomething = True
                    break
                else:
                    command = previousCommand
                    arguments = shlex.split(command)
        if not changedSomething:
            break

if removeUrlParameters:
    print('Removing URL parameters')

    arguments = shlex.split(command)
    for argumentsIndex, argument in enumerate(arguments):
        if re.match('https?://', argument):
            urlIndex = argumentsIndex
            break

    def getUrl(urlParsed, query):
        return urlParsed._replace(query = '&'.join([f'{quote_plus(parameter)}={quote_plus(query[parameter][0])}' for parameter in query])).geturl()

    url = arguments[urlIndex]
    previousKeyIndex = 0
    while True:
        changedSomething = False
        urlParsed = urlparse(url)
        query = parse_qs(urlParsed.query, keep_blank_values = True)
        for keyIndex, key in enumerate(list(query)[previousKeyIndex:]):
            previousQuery = copy.deepcopy(query)
            printTryToRemove(key)
            del query[key]
            # Make a function with below code.
            url = getUrl(urlParsed, query)
            arguments[urlIndex] = url
            command = shlex.join(arguments)
            if isCommandStillFine(command):
                printThatCommandIsStillFine(command)
                changedSomething = True
                previousKeyIndex = keyIndex
                break
            else:
                query = previousQuery
                url = getUrl(urlParsed, query)
                arguments[urlIndex] = url
                command = shlex.join(arguments)
        if not changedSomething:
            break

if removeCookies:
    print('Removing cookies')

    COOKIES_PREFIX = 'Cookie: '
    COOKIES_PREFIX_LEN = len(COOKIES_PREFIX)

    cookiesIndex = None
    arguments = shlex.split(command)
    for argumentsIndex, argument in enumerate(arguments):
        # For Chromium support:
        if argument[:COOKIES_PREFIX_LEN].title() == COOKIES_PREFIX:
            cookiesIndex = argumentsIndex
            arguments[cookiesIndex] = COOKIES_PREFIX + argument[COOKIES_PREFIX_LEN:]
            break

    if cookiesIndex is not None:
        cookies = arguments[cookiesIndex]
        previousCookiesParsedIndex = 0
        while True:
            changedSomething = False
            cookiesParsed = cookies.replace(COOKIES_PREFIX, '').split('; ')
            for cookiesParsedIndex, cookie in enumerate(cookiesParsed[previousCookiesParsedIndex:]):
                cookiesParsedCopy = cookiesParsed[:]
                printTryToRemove(cookie)
                del cookiesParsedCopy[cookiesParsedIndex]
                arguments[cookiesIndex] = COOKIES_PREFIX + '; '.join(cookiesParsedCopy)
                command = shlex.join(arguments)
                if isCommandStillFine(command):
                    printThatCommandIsStillFine(command)
                    changedSomething = True
                    previousCookiesParsedIndex = cookiesParsedIndex
                    cookies = '; '.join(cookiesParsedCopy)
                    break
                else:
                    arguments[cookiesIndex] = COOKIES_PREFIX + '; '.join(cookiesParsed)
                    command = shlex.join(arguments)
            if not changedSomething:
                break

if removeRawData:
    print('Removing raw data')

    rawDataIndex = None
    isJson = False
    arguments = shlex.split(command)
    for argumentsIndex, argument in enumerate(arguments):
        if argumentsIndex > 0 and arguments[argumentsIndex - 1] == '--data-raw':
            rawDataIndex = argumentsIndex
            try:
                json.loads(argument)
                isJson = True
            except:
                pass
            break

    if rawDataIndex is not None:
        rawData = arguments[rawDataIndex]
        # Could interwine both cases but don't seem to clean much the code due to `getPaths` notably.
        # Just firstly making a common function to all parts minimizer would make sense.
        if not isJson:
            previousRawDataPartsIndex = 0
            while rawData != '':
                changedSomething = False
                rawDataParts = rawData.split('&')
                for rawDataPartsIndex, rawDataPart in enumerate(rawDataParts[previousRawDataPartsIndex:]):
                    rawDataPartsCopy = copy.deepcopy(rawDataParts)
                    printTryToRemove(rawDataPartsCopy[rawDataPartsIndex])
                    del rawDataPartsCopy[rawDataPartsIndex]
                    arguments[rawDataIndex] = '&'.join(rawDataPartsCopy)
                    command = shlex.join(arguments)
                    if isCommandStillFine(command):
                        printThatCommandIsStillFine(command)
                        changedSomething = True
                        previousRawDataPartsIndex = rawDataPartsIndex
                        rawData = '&'.join(rawDataPartsCopy)
                        break
                    else:
                        arguments[rawDataIndex] = '&'.join(rawDataParts)
                        command = shlex.join(arguments)
                if not changedSomething:
                    break
        # JSON recursive case.
        else:
            def getPaths(d):
                if isinstance(d, dict):
                    for key, value in d.items():
                        yield f'/{key}'
                        yield from (f'/{key}{p}' for p in getPaths(value))

                elif isinstance(d, list):
                    for i, value in enumerate(d):
                        yield f'/{i}'
                        yield from (f'/{i}{p}' for p in getPaths(value))

            # If a single unknown entry is necessary, then this algorithm seems to most efficiently goes from parents to children if necessary to remove other entries. Hence, it seems to proceed in a linear number of HTTPS requests and not a quadratic one.
            # Try until no more change to remove unnecessary entries. If assume a logical behavior as just mentioned, would not a single loop iteration be enough? Not with current design, see (1).
            previousPathsIndex = 0
            while True:
                changedSomething = False
                rawDataParsed = json.loads(rawData)
                # Note that the path goes from parents to children if necessary which is quite a wanted behavior to quickly remove useless chunks.
                paths = getPaths(rawDataParsed)
                # For all entries, copy current `rawData` and try to remove an entry.
                for pathsIndex, path in enumerate(list(paths)[previousPathsIndex:]):
                    # Copy current `rawData`.
                    rawDataParsedCopy = copy.deepcopy(rawDataParsed)
                    # Remove an entry.
                    # Pay attention that integer keys need to be consider as such, so not as `str` as face a `list` instead of a `dict`.
                    entry = rawDataParsedCopy
                    pathParts = path[1:].split('/')
                    for pathPart in pathParts[:-1]:
                        pathPart = pathPart if not pathPart.isdigit() else int(pathPart)
                        entry = entry[pathPart]
                    lastPathPart = pathParts[-1]
                    lastPathPart = lastPathPart if not lastPathPart.isdigit() else int(lastPathPart)
                    printTryToRemove(path)
                    del entry[lastPathPart]
                    # Test if the removed entry was necessary.
                    arguments[rawDataIndex] = json.dumps(rawDataParsedCopy)
                    command = shlex.join(arguments)
                    # (1) If it was unnecessary, then reconsider paths excluding possible children paths of this unnecessary entry, ensuring optimized complexity it seems.
                    if isCommandStillFine(command):
                        printThatCommandIsStillFine(command)
                        changedSomething = True
                        previousPathsIndex = pathsIndex
                        rawData = json.dumps(rawDataParsedCopy)
                        break
                    # If it was necessary, we consider possible children paths of this necessary entry and other paths.
                    else:
                        arguments[rawDataIndex] = json.dumps(rawDataParsed)
                        command = shlex.join(arguments)
                # If a loop iteration considering all paths, does not change anything, then the request cannot be minimized further.
                if not changedSomething:
                    break

command = command.replace(' --compressed', '')
command = command.replace(' --data-raw \'\'', '')

HTTP_METHOD = ' -X POST'

if HTTP_METHOD in command:
    previousCommand = command
    command = command.replace(HTTP_METHOD, '')
    if not isCommandStillFine(command):
        command = previousCommand

# First test `print`ing, before potentially removing `minimized_curl` writing.
print(command)
writeCommand('minimized_curl', command)

os.remove(getCommandScript(PARTIALLY_MINIMIZED_CURL_SCRIPT_NAME))
