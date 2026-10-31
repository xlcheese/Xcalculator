# Xcalculator: build the translations and install the program.
#
#   make           compile po/*.po and write the menu entry with its translations
#   make pot       update po/xcalculator.pot from the source (after changing any text)
#   make install   copy everything into $(DESTDIR)$(PREFIX); debian/rules runs this
#   make clean     remove what make built

APP_ID  = io.github.xlcheese.Xcalculator
DOMAIN  = xcalculator
VERSION = $(shell sed -n '1s/.*(\(.*\)).*/\1/p' debian/changelog)
PREFIX ?= /usr

PROGRAM = usr/lib/xcalculator
SOURCES = $(sort $(wildcard $(PROGRAM)/*.py))
DESKTOP = usr/share/applications/$(APP_ID).desktop
LOCALE  = usr/share/locale
LANGUAGES = $(shell grep -v "^\s*#" po/LINGUAS)
MO_FILES  = $(foreach lang,$(LANGUAGES),$(LOCALE)/$(lang)/LC_MESSAGES/$(DOMAIN).mo)
# the menu entry's words that are translated (its Name, Xcalculator, is not)
DESKTOP_KEYWORDS = --keyword= --keyword=GenericName --keyword=Comment --keyword=Keywords

all: $(MO_FILES) $(DESKTOP)

$(LOCALE)/%/LC_MESSAGES/$(DOMAIN).mo: po/%.po
	mkdir -p $(dir $@)
	msgfmt --check --output-file=$@ $<

$(DESKTOP): data/$(APP_ID).desktop.in $(wildcard po/*.po)
	mkdir -p $(dir $@)
	msgfmt --desktop $(DESKTOP_KEYWORDS) --template=$< -d po --output-file=$@

POT_HEADER = --package-name=Xcalculator --package-version=$(VERSION) --copyright-holder="Wesley Hayslip" \
	--msgid-bugs-address=https://github.com/xlcheese/Xcalculator/issues

pot:
	xgettext --language=Python --from-code=UTF-8 --keyword=_ --keyword=N_ --add-comments=Translators \
		$(POT_HEADER) --output=po/$(DOMAIN).pot $(SOURCES)
	xgettext --language=Desktop $(DESKTOP_KEYWORDS) --add-comments=Translators --join-existing \
		$(POT_HEADER) --output=po/$(DOMAIN).pot data/$(APP_ID).desktop.in
	for po in $(wildcard po/*.po); do msgmerge --quiet --update --backup=none $$po po/$(DOMAIN).pot; done

install: all
	install -d $(DESTDIR)$(PREFIX)/bin
	sed 's|/usr/lib/xcalculator/|$(PREFIX)/lib/xcalculator/|' usr/bin/xcalculator > $(DESTDIR)$(PREFIX)/bin/xcalculator
	chmod 755 $(DESTDIR)$(PREFIX)/bin/xcalculator
	install -d $(DESTDIR)$(PREFIX)/lib/xcalculator
	install -m644 $(SOURCES) $(DESTDIR)$(PREFIX)/lib/xcalculator/
	chmod 755 $(DESTDIR)$(PREFIX)/lib/xcalculator/xcalculator.py
	install -Dm644 $(DESKTOP) $(DESTDIR)$(PREFIX)/share/applications/$(APP_ID).desktop
	install -Dm644 usr/share/metainfo/$(APP_ID).metainfo.xml $(DESTDIR)$(PREFIX)/share/metainfo/$(APP_ID).metainfo.xml
	install -Dm644 usr/share/man/man1/xcalculator.1 $(DESTDIR)$(PREFIX)/share/man/man1/xcalculator.1
	for size in scalable 16x16 24x24 32x32; do \
		install -Dm644 usr/share/icons/hicolor/$$size/apps/$(APP_ID).svg \
			$(DESTDIR)$(PREFIX)/share/icons/hicolor/$$size/apps/$(APP_ID).svg; \
	done
	install -d $(DESTDIR)$(PREFIX)/lib/systemd/user
	for unit in xcalculator-rates.service xcalculator-rates.timer; do \
		sed 's|@BINDIR@|$(PREFIX)/bin|' data/$$unit.in > $(DESTDIR)$(PREFIX)/lib/systemd/user/$$unit; \
		chmod 644 $(DESTDIR)$(PREFIX)/lib/systemd/user/$$unit; \
	done
	for lang in $(LANGUAGES); do \
		install -Dm644 $(LOCALE)/$$lang/LC_MESSAGES/$(DOMAIN).mo \
			$(DESTDIR)$(PREFIX)/share/locale/$$lang/LC_MESSAGES/$(DOMAIN).mo; \
	done

clean:
	rm -rf $(LOCALE) usr/share/applications

.PHONY: all pot install clean
