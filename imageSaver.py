# -*- coding: utf-8 -*-

import LikedSavedDatabase
import imgurDownloader
import json
import logger
import os
import random
import re
import settings
import submission as Submissions
import sys
import utilities
import videoDownloader

from builtins import str
from crcUtils import signedCrc32
from gfycat.client import GfycatClient
from operator import attrgetter

import urllib
if sys.version_info[0] >= 3:
	from urllib.request import urlretrieve, urlopen
        #from urllib.request import urlopen
else:
	from urllib import urlretrieve, urlopen

SupportedTypes = ['jpg', 'jpeg', 'gif', 'png', 'webm', 'mp4']

def getFileTypeFromUrl(url):
    if url and url.find('.') != -1 and url.rfind('.') > url.rfind('/'):
        return url[url.rfind('.') + 1:]
    else:
        return ''

# Helper function. Print percentage complete
def percentageComplete(currentItem, numItems):
    if numItems:
        return str(int(((float(currentItem + 1) / float(numItems)) * 100))) + '%'

    return 'Invalid'

def isUrlSupportedType(url):
    urlFileType = getFileTypeFromUrl(url)
    return urlFileType in SupportedTypes

def getUrlContentType(url):
    if url:
        openedUrl = None
        try:
            openedUrl = urlopen(url)
        except IOError as e:
            logger.log('[ERROR] IOError: Url {0} raised exception:\n\t{1} {2}'
                .format(url, e.errno, e.strerror))
        except Exception as e:
            logger.log('[ERROR] Exception: Url {0} raised exception:\n\t {1}'
                        .format(url, e))
            logger.log('[ERROR] Url ' + url + 
                ' raised an exception I did not handle. Open an issue at '
                '\n\thttps://github.com/makuto/redditLikedSavedImageDownloader/issues'
                '\n and I will try to fix it')
        else:
            if sys.version_info[0] >= 3:
                return openedUrl.info().get_content_subtype()
            else:
                return openedUrl.info().subtype
    return ''

def isContentTypeSupported(contentType):
    # JPGs are JPEG
    supportedTypes = SupportedTypes + ['jpeg']
    return contentType.lower() in supportedTypes

def convertContentTypeToFileType(contentType):
    # Special case: we want all our JPEGs to be .jpg :(
    if contentType.lower() == 'jpeg':
        return 'jpg'

    return contentType

# Find the source of an image by reading the url's HTML, looking for sourceKey
# An example key would be '<img src='. Note that the '"' will automatically be 
#  recognized as part of the key, so do not specify it
# If sourceKeyAttribute is specified, sourceKey will first be found, then 
#  the line will be searched for sourceKeyAttribute (e.g. sourceKey = '<img' and 
#  sourceKeyAttribute = 'src=').
def findSourceFromHTML(url, sourceKey, sourceKeyAttribute=''):
    SANE_NUM_LINES = 30

    # Open the page to search for a saveable .gif or .webm
    try:
        pageSource = urlopen(url)
    except urllib.error.HTTPError as e:
        print("URL {} had HTTP error:\n{}".format(url, str(e.reason)))
        return None

    # This code doesn't quite work yet; if things are breaking near here you're not reading a .html
    # Leaving this here for future work
    pageEncoding = None
    if sys.version_info[0] >= 3:
        pageEncoding = pageSource.headers.get_content_charset()
        #logger.log(pageSource.headers.get_content_subtype())
        #logger.log(url)
        
    pageSourceLines = pageSource.readlines()
    pageSource.close()

    # If a page has fewer than this number of lines, there is something wrong.
    # This is a somewhat arbitrary heuristic
    if len(pageSourceLines) <= SANE_NUM_LINES:
        logger.log('Url "' + url + '" has a suspicious number of lines (' + str(len(pageSourceLines)) + ')')

    for line in pageSourceLines:
        lineStr = line
        if sys.version_info[0] >= 3 and pageEncoding:
            # If things are breaking near here you're not reading a .html    
            lineStr = line.decode(pageEncoding)

        try:
            foundSourcePosition = lineStr.lower().find(sourceKey.lower())
        # Probably not reading a text file; we won't be able to determine the type
        except TypeError:
            logger.log('Unable to guess type for Url "' + url)
            return ''
        
        if foundSourcePosition > -1:
            urlStartPosition = -1
            if sourceKeyAttribute:
                attributePosition = lineStr[foundSourcePosition:].lower().find(sourceKeyAttribute.lower())
                # Find the first character of the URL specified by the attribute (add 1 for the ")
                urlStartPosition = foundSourcePosition + attributePosition + len(sourceKeyAttribute) + 1
            else:
                # Find the first character of the URL (add 1 for the ")
                urlStartPosition = foundSourcePosition + len(sourceKey) + 1

            # From the start of the url, search for the next '"' which is the end of the src link
            urlEndPosition = lineStr[urlStartPosition:].find('"')

            if urlEndPosition > -1:
                sourceUrl = lineStr[urlStartPosition:urlStartPosition + urlEndPosition]

                return sourceUrl

    return ''

def isGfycatUrl(url):
    return ('gfycat' in url.lower()
            and '.webm' not in url.lower()
            and '.gif' not in url.lower()[-4:])

# Lazy initialize in case it's not needed
gfycatClient = None
# Special handling for Gfycat links
# Returns a URL to a webm which can be downloaded by urllib
def convertGfycatUrlToWebM(url):
    global gfycatClient
    # Change this:
    #   https://gfycat.com/IndolentScalyIncatern
    #   https://gfycat.com/IndolentScalyIncatern/
    # Into this:
    #   https://zippy.gfycat.com/IndolentScalyIncatern.webm
    # Or maybe this:
    #   https://giant.gfycat.com/IndolentScalyIncatern.webm

    # Lazy initialize client
    if not gfycatClient and settings.settings['Gfycat_Client_id']:
        gfycatClient = GfycatClient(settings.settings['Gfycat_Client_id'],settings.settings['Gfycat_Client_secret'])

    # Still don't have a client?
    if not gfycatClient:
        # Hacky solution while Gfycat API isn't set up. This breaks if case is wrong
        return "https://giant.gfycat.com/{}.webm".format(url[url.rfind("/") + 1:])
    else:
        # Get the gfyname from the url
        matches = re.findall(r'gfycat\.com.*/([a-zA-Z]+)', url)
        if not matches:
            logger.log("Gfycat URL {} doesn't seem to match expected URL format")
        else:
            try:
                gfycatUrlInfo = gfycatClient.query_gfy(matches[0])
            except Exception as e:
                logger.log('[ERROR] Exception: Url {0} raised exception:\n\t {1}'
                           .format(url, e))
                return None
            return gfycatUrlInfo['gfyItem']['mp4Url']

def isGifVUrl(url):
    return getFileTypeFromUrl(url) == 'gifv'

# Special handling for Imgur's .gifv
def convertGifVUrlToWebM(url):
    # Find the source link
    GIFV_SOURCE_KEY = '<source src='
    gifvSource = findSourceFromHTML(url, GIFV_SOURCE_KEY)

    # Didn't work? Try the alternate key
    if not gifvSource:
        ALTERNATE_GIFV_SOURCE_KEY = '<meta itemprop="contentURL" content='
        gifvSource = findSourceFromHTML(url, ALTERNATE_GIFV_SOURCE_KEY)

    # Still nothing? Try text hacking .mp4 onto the link and hope it's valid
    if not gifvSource:
        gifvSource = url[:-5] + '.mp4'

    # For whatever reason, Imgur has this screwy no http(s) on their source links sometimes
    if gifvSource and gifvSource[:2] == '//':
        gifvSource = 'http:' + gifvSource

    return gifvSource

# Make sure the filename is alphanumeric or has supported symbols, and is shorter than 45 characters
def safeFileName(filename, file_path = False):
    acceptableChars = ['_', ' ']
    safeName = ''

    # If we are making a file path safe, allow / and \
    if file_path:
        acceptableChars += ['/', '\\']

    for char in filename:
        if char.isalnum() or char in acceptableChars:
            safeName += char

    # If there were no valid characters, give it a random number for a unique title
    if not safeName:
        safeName = 'badName_' + str(random.randint(1, 1000000))

    if not file_path:
        MAX_NAME_LENGTH = 250
        if len(safeName) > MAX_NAME_LENGTH:
            safeName = safeName[:MAX_NAME_LENGTH]

    return safeName

# Save the images in directories based on subreddits
# Name the images based on their submission titles
# Returns a list of submissions which didn't have supported image formats
def saveAllImages(outputDir, submissions, imgur_auth = None, only_download_albums = False,
                  skip_n_percent_submissions = 0, 
                  soft_retrieve_imgs = False, only_important_messages = False):
    numSavedImages = 0
    numAlreadySavedImages = 0
    numAlreadySavedVideos = 0
    numSavedVideos = 0
    numUnsupportedImages = 0
    numUnsupportedAlbums = 0
    numUnsupportedVideos = 0

    unsupportedSubmissions = []

    # Dictionary where key = subreddit and value = list of (submissionTitle, imgur album urls)
    imgurAlbumsToSave = {}

    if not soft_retrieve_imgs:
        utilities.makeDirIfNonexistant(outputDir)
    
    # Sort by subreddit, alphabetically
    sortedSubmissions = sorted(submissions, key=attrgetter('subreddit'))

    # Start further into the list (in case the script failed early or something and you don't want 
    #  to redownload everything)
    if skip_n_percent_submissions:
        newFirstSubmissionIndex = int((len(sortedSubmissions) / 100) * skip_n_percent_submissions)
        sortedSubmissions = sortedSubmissions[newFirstSubmissionIndex:]

        logger.log('Starting at ' + str(skip_n_percent_submissions) + '%; skipped ' +
            str(newFirstSubmissionIndex) + ' submissions')

    submissionsToSave = len(sortedSubmissions)

    for currentSubmissionIndex, submission in enumerate(sortedSubmissions):
        url = submission.bodyUrl
        subredditDir = submission.subreddit[3:-1] if submission.source == u'reddit' else safeFileName(submission.subredditTitle)
        submissionTitle = submission.title
        # Always trust tumblr submissions because we know 100% they're images
        shouldTrustUrl = (submission.source == u'Tumblr')
        # Always use tumblr Submission titles because we generate them in tumblrScraper
        shouldTrustTitle = (submission.source == u'Tumblr')

        if not url:
            continue

        urlContentType = ''

        if videoDownloader.shouldUseYoutubeDl(url):
            result = videoDownloader.downloadVideo(outputDir + u'/' + subredditDir, url)
            if not result[0]:
                if result[1] == videoDownloader.alreadyDownloadedSentinel:
                    numAlreadySavedVideos += 1
                else:
                    logger.log('[' + percentageComplete(currentSubmissionIndex, submissionsToSave) + '] '
                               + ' [unsupported] ' + 'Failed to retrieve "' + url + '" (video). Reason: ' + result[1])
                    LikedSavedDatabase.db.addUnsupportedSubmission(submission, result[1])
                    numUnsupportedVideos += 1
            else:
                logger.log('[' + percentageComplete(currentSubmissionIndex, submissionsToSave) + '] '
                           + ' [save] ' + 'Saved "' + url + '" (video) to ' + result[1])
                LikedSavedDatabase.db.associateFileToSubmission(
                    utilities.outputPathToDatabasePath(result[1]), submission)
                numSavedVideos += 1
            continue
        elif settings.settings['Only_download_videos'] and not 'gfycat' in url:
            logger.log("Skipped {} due to 'Only download videos' setting".format(url))
            continue

        if not shouldTrustUrl:
            # Imgur Albums have special handling
            if imgurDownloader.isImgurAlbumUrl(url):
                if not imgur_auth:
                    logger.log('[' + percentageComplete(currentSubmissionIndex, submissionsToSave) + '] '
                        + ' [unsupported] ' + 'Skipped "' + url + '" (imgur album)')
                    LikedSavedDatabase.db.addUnsupportedSubmission(submission, "Imgur albums not supported")
                    numUnsupportedAlbums += 1
                    continue
                else:
                    # We're going to save Imgur Albums at a separate stage
                    if subredditDir in imgurAlbumsToSave:
                        imgurAlbumsToSave[subredditDir].append((submission, submissionTitle, url))
                    else:
                        imgurAlbumsToSave[subredditDir] = [(submission, submissionTitle, url)]
                    continue
            elif only_download_albums:
                continue

            # Massage special-case links so that they can be downloaded
            if isGfycatUrl(url):
                url = convertGfycatUrlToWebM(url)
            elif isGifVUrl(url):
                url = convertGifVUrlToWebM(url)
            elif imgurDownloader.isImgurIndirectUrl(url):
                url = imgurDownloader.convertImgurIndirectUrlToImg(url)

            if url:
                urlContentType = getUrlContentType(url)
            else:
                continue

        if shouldTrustUrl or isUrlSupportedType(url) or isContentTypeSupported(urlContentType):
            fileType = getFileTypeFromUrl(url)
            if not fileType:
                fileType = convertContentTypeToFileType(urlContentType)

            if not shouldTrustUrl:
                # If the file path doesn't match the content type, it's possible it's incorrect 
                #  (e.g. a .png labeled as a .jpg)
                contentFileType = convertContentTypeToFileType(urlContentType)
                if contentFileType != fileType and (contentFileType != 'jpg' and fileType != 'jpeg'):
                    logger.log('WARNING: Content type "' + contentFileType 
                        + '" was going to be saved as "' + fileType + '"! Correcting.')
                    if contentFileType == 'html':
                        logger.log('[' + percentageComplete(currentSubmissionIndex, submissionsToSave) + '] '
                            + ' [unsupported] ' + 'Skipped "' + url 
                            + '" (file is html, not image; this might mean Access was Denied)')
                        numUnsupportedImages += 1
                        continue

                    fileType = contentFileType

            if shouldTrustTitle:
                saveFilePath = (outputDir + u'/' + subredditDir + u'/' 
                    + safeFileName(submissionTitle) + u'.' + fileType)
            else:
                # Example path:
                # output/aww/My Cute Kitten_802984323.png
                # output/subreddit/Submission Title_urlCRC.fileType
                # The CRC is used so that if we are saving two images with the same
                #  post title (e.g. 'me_irl') we get unique filenames because the URL is different
                saveFilePath = (outputDir + u'/' + subredditDir + u'/' + safeFileName(submissionTitle) 
                                + u'_' + str(signedCrc32(url.encode())) + u'.' + fileType)

                # Maybe not do this? Ubuntu at least can do Unicode folders etc. just fine
                #saveFilePath = safeFileName(saveFilePath, file_path = True)

            # If we already saved the image, skip it
            # TODO: Try not to make make any HTTP requests on skips...
            if os.path.isfile(saveFilePath):
                if not only_important_messages:
                    logger.log('[' + percentageComplete(currentSubmissionIndex, submissionsToSave) + '] ' 
                        + ' [already saved] ' + 'Skipping ' + saveFilePath)
                numAlreadySavedImages += 1
                continue

            if not soft_retrieve_imgs:
                # Make directory for subreddit
                utilities.makeDirIfNonexistant(outputDir + '/' + subredditDir)

                # Retrieve the image and save it
                try:
                    urlretrieve(url, saveFilePath)

                    LikedSavedDatabase.db.associateFileToSubmission(
                            utilities.outputPathToDatabasePath(saveFilePath), submission)
                except IOError as e:
                    errorMessage = '[ERROR] IOError: Url {0} raised exception:\n\t{1} {2}'.format(url, e.errno, e.strerror)
                    logger.log(errorMessage)
                    LikedSavedDatabase.db.addUnsupportedSubmission(submission, errorMessage)
                    numUnsupportedImages += 1
                    continue
                except KeyboardInterrupt:
                    exit()
                except Exception as e:
                    errorMessage = '[ERROR] Exception: Url {0} raised exception:\n\t {1}'.format(url, e)
                    logger.log(errorMessage)
                    logger.log('[ERROR] Url ' + url + 
                        ' raised an exception I did not handle. Open an issue at '
                        '\n\thttps://github.com/makuto/redditLikedSavedImageDownloader/issues'
                        '\n and I will try to fix it')
                    LikedSavedDatabase.db.addUnsupportedSubmission(submission, errorMessage)
                    numUnsupportedImages += 1
                    continue

            # Output our progress
            logger.log('[' + percentageComplete(currentSubmissionIndex, submissionsToSave) + '] ' 
                    + ' [save] ' + url + ' saved to "' + subredditDir + '"')
            numSavedImages += 1

        else:
            logger.log('[' + percentageComplete(currentSubmissionIndex, submissionsToSave) + '] '
                + ' [unsupported] ' + 'Skipped "' + url + '" (content type "' + urlContentType + '")')
            unsupportedSubmissions.append(submission)
            LikedSavedDatabase.db.addUnsupportedSubmission(submission,
                                                           "URL or content type {} not supported".format(urlContentType))
            numUnsupportedImages += 1

    numSavedAlbums = 0
    if imgur_auth and imgurAlbumsToSave:
        numSavedAlbums = imgurDownloader.saveAllImgurAlbums(outputDir, imgur_auth, imgurAlbumsToSave, 
                                                            soft_retrieve_imgs = soft_retrieve_imgs)

    logger.log('Good:')
    logger.log('\t Saved Images: {}'.format(numSavedImages))
    logger.log('\t Already Saved Images: {}'.format(numAlreadySavedImages))
    logger.log('\t Saved Albums: {}'.format(numSavedAlbums))
    logger.log('\t Saved Videos: {}'.format(numSavedVideos))
    logger.log('\t Already Saved Videos: {}'.format(numAlreadySavedVideos))
    logger.log('Bad:')
    logger.log('\t Unsupported Images: {}'.format(numUnsupportedImages))
    logger.log('\t Unsupported Albums: {}'.format(numUnsupportedAlbums))
    logger.log('\t Unsupported Videos: {}'.format(numUnsupportedVideos))

    return unsupportedSubmissions

def loadSubmissionsFromJson(filename):
    file = open(filename, 'r')
    # Ugh...
    lines = file.readlines()
    text = u''.join(lines)
    # Fix the formatting so the json module understands it
    text = "[{}]".format(text[1:-3])
        
    dictSubmissions = json.loads(text)
    submissions = []
    for dictSubmission in dictSubmissions:
        submission = Submissions.Submission()
        submission.initFromDict(dictSubmission)
        submissions.append(submission)

    return submissions

if __name__ == '__main__':
    print("Running image saver tests")

    outputDirOverride = 'LOCAL_testOutput'
    utilities.makeDirIfNonexistant(outputDirOverride)
    
    settings.getSettings()
    LikedSavedDatabase.initializeFromSettings(settings.settings)
    
    # Temporary override
    settings.settings['Output_dir'] = outputDirOverride
    
    testSubmissions = loadSubmissionsFromJson('LOCAL_imageSaver_test_submissions.json')
    if testSubmissions:
        imgurAuth = None
        if (settings.settings['Should_download_albums'] 
            and settings.hasImgurSettings()):
            imgurAuth = imgurDownloader.ImgurAuth(settings.settings['Imgur_client_id'], 
                                                  settings.settings['Imgur_client_secret'])
        else:
            logger.log('No Imgur Client ID and/or Imgur Client Secret was provided, or album download is not'
                       ' enabled. This is required to download imgur albums. They will be ignored. Check'
                       ' settings.txt for how to fill in these values.')
        
        unsupportedSubmissions = saveAllImages(outputDirOverride, testSubmissions, 
                                               imgur_auth = imgurAuth,
                                               only_download_albums = settings.settings['Only_download_albums'],
                                               skip_n_percent_submissions = settings.settings['Skip_n_percent_submissions'],
                                               soft_retrieve_imgs = settings.settings['Should_soft_retrieve'],
                                               only_important_messages = settings.settings['Only_important_messages'])
    else:
        print("No submissions found")
