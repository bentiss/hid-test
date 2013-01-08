noinst_PROGRAMS =

bin_PROGRAMS = xi2detach

INCLUDES=-I$(top_srcdir)/include/

AM_CFLAGS = $(XINPUT_CFLAGS)
xi2detach_LDADD = $(XINPUT_LIBS)

# man page generation
if HAVE_DOCTOOLS
# actual man pages
man_pages_sources = xi2detach.txt
# shadow man pages
man_pages_shadows =

man_pages = $(man_pages_sources:.txt=.1) $(man_pages_shadows)

SUFFIXES = .1 .txt .xml

.xml.1:
	@$(XMLTO) man $<

.txt.xml:
	@$(ASCIIDOC) -b docbook -d manpage -o $@ $<

dist_man_MANS = $(man_pages)
CLEANFILES = $(dist_man_MANS)
MAINTAINERCLEANFILES = $(man_pages) *.xml
endif
