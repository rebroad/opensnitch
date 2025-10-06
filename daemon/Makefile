#SRC contains all *.go *.c *.h files in daemon/ and its subfolders 
SRC := $(shell find . -type f -name '*.go' -o -name '*.h' -o -name '*.c')
PREFIX?=/usr/local

all: opensnitchd

install:
	@mkdir -p $(DESTDIR)/etc/opensnitchd/rules
	@mkdir -p $(DESTDIR)/etc/opensnitchd/tasks
	@install -Dm755 opensnitchd \
		-t $(DESTDIR)$(PREFIX)/bin/
	@install -Dm644 opensnitchd.service \
		-t $(DESTDIR)/etc/systemd/system/
	@if [ ! -f $(DESTDIR)/etc/opensnitchd/default-config.json ]; then \
		install -Dm644 default-config.json -t $(DESTDIR)/etc/opensnitchd/; \
		echo "Installed default-config.json (file did not exist)"; \
	else \
		echo "Skipping default-config.json (file already exists - preserving your configuration)"; \
	fi
	@if [ ! -f $(DESTDIR)/etc/opensnitchd/system-fw.json ]; then \
		install -Dm644 system-fw.json -t $(DESTDIR)/etc/opensnitchd/; \
		echo "Installed system-fw.json (file did not exist)"; \
	else \
		echo "Skipping system-fw.json (file already exists - preserving your configuration)"; \
	fi
	@if [ ! -f $(DESTDIR)/etc/opensnitchd/network_aliases.json ]; then \
		install -Dm644 network_aliases.json -t $(DESTDIR)/etc/opensnitchd/; \
		echo "Installed network_aliases.json (file did not exist)"; \
	else \
		echo "Skipping network_aliases.json (file already exists - preserving your configuration)"; \
	fi
	@install -Dm600 data/rules/* $(DESTDIR)/etc/opensnitchd/rules/
	@install -Dm600 data/tasks/tasks.json $(DESTDIR)/etc/opensnitchd/tasks/
	@systemctl daemon-reload

opensnitchd: $(SRC)
	@go get
	@go build -o opensnitchd . 

clean:
	@rm -rf opensnitchd


