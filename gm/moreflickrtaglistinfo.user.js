// ==UserScript==
// @name           More Flickr Tag List Info
// @namespace      http://trentm.com/
// @description    Show some more info about a photo in a tag list
// @include        http://www.flickr.com/photos/trento/tags/*
// ==/UserScript==

var td = document.getElementById("GoodStuff"); // holds all the thumbnails
var div = td.getElementsByTagName("div")[0];
var ps = div.getElementsByTagName("p");
for (i=0; i < ps.length; i++) {
    p = ps[i];
    a = p.getElementsByTagName('a')[0];
    p.appendChild(document.createElement('br'));
    p.appendChild(document.createTextNode("title: "+a.getAttribute("title")));
}

