# Initialize Autoconf
AC_PREREQ([2.60])
AC_INIT([HID test suite],
        [1.0.0],
        [],
        [])
AC_CONFIG_SRCDIR([Makefile.am])
AC_CONFIG_HEADERS([config.h])
AC_CONFIG_AUX_DIR([config-aux])

# Initialize Automake
AM_INIT_AUTOMAKE([foreign dist-bzip2])
AM_MAINTAINER_MODE

LIB_VERSION=1:0:0
AC_SUBST([LIB_VERSION])

# Checks for programs.
AC_PROG_CC
AC_PROG_INSTALL

# man page generation
AC_ARG_VAR([XMLTO], [Path to xmlto command])
AC_PATH_PROG([XMLTO], [xmlto])
AC_ARG_VAR([ASCIIDOC], [Path to asciidoc command])
AC_PATH_PROG([ASCIIDOC], [asciidoc])
AM_CONDITIONAL([HAVE_DOCTOOLS], [test "x$XMLTO" != "x" && test "x$ASCIIDOC" != "x"])
if test "x$XMLTO" = "x" || test "x$ASCIIDOC" = "x"; then
	AC_MSG_WARN([xmlto or asciidoc not found - cannot create man pages without it])
fi

# Require X.Org macros 1.8 or later for MAN_SUBSTS set by XORG_MANPAGE_SECTIONS
#m4_ifndef([XORG_MACROS_VERSION],
#          [m4_fatal([must install xorg-macros 1.8 or later before running autoconf/autogen])])
#XORG_MACROS_VERSION(1.8)
XORG_DEFAULT_OPTIONS

# Obtain compiler/linker options for dependencies
PKG_CHECK_MODULES(XINPUT, x11 xext [xi >= 1.2] [inputproto >= 1.5] xrandr xinerama)

# XI2 support
PKG_CHECK_MODULES(XI2, [xi >= 1.2.99.2] [inputproto >= 1.9.99.15],
                  HAVE_XI2="yes"; AC_DEFINE(HAVE_XI2, 1, [XI2 available]),
                  HAVE_XI2="no");
AM_CONDITIONAL(HAVE_XI2, [ test "$HAVE_XI2" = "yes" ])
AC_SUBST(HAVE_XI2)

# XI2.1 support
PKG_CHECK_MODULES(XI21, [xi >= 1.4.99.1] [inputproto >= 2.0.99.1],
                  AC_DEFINE(HAVE_XI21, 1, [XI2.1 available]));


AC_CONFIG_FILES([Makefile
                 src/Makefile])
AC_OUTPUT
