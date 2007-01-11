#!/usr/bin/python

import sys
from flickrapi import FlickrAPI

# flickr auth information:
flickrAPIKey = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # API key
flickrSecret = "yyyyyyyyyyyyyyyy"                  # shared "secret"

# make a new FlickrAPI instance
fapi = FlickrAPI(flickrAPIKey, flickrSecret)

# do the whole whatever-it-takes to get a valid token:
token = fapi.getToken(browser="firefox")

# get my favorites
rsp = fapi.favorites_getList(api_key=flickrAPIKey,auth_token=token)
fapi.testFailure(rsp)

# and print them
for a in rsp.photos[0].photo:
	print "%10s: %s" % (a['id'], a['title'].encode("ascii", "replace"))

# upload the file foo.jpg
#fp = file("foo.jpg", "rb")
#data = fp.read()
#fp.close()
#rsp = fapi.upload(jpegData=data, api_key=flickrAPIKey, auth_token=token, \
#rsp = fapi.upload(filename="foo.jpg", api_key=flickrAPIKey, auth_token=token, \
#	title="This is the title", description="This is the description", \
#	tags="tag1 tag2 tag3",\
#	is_friend="1", is_public="0", is_family="1")
#fapi.testFailure(rsp)

