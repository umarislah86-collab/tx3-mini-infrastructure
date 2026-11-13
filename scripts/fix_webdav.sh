#!/bin/bash
sed -i 's/ --path-prefix \/webdav//g' /etc/systemd/system/webdav.service
systemctl daemon-reload
systemctl restart webdav
systemctl status webdav --no-pager
