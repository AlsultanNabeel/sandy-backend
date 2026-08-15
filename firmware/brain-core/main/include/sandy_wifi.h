#pragma once
#include "esp_err.h"
#include <stdbool.h>

esp_err_t wifi_sandy_start(void);
bool      wifi_sandy_is_connected(void);

// آخر عنوان أخذه اللوح، أو نص فاضي لو لسا ما أخذ. بينحط بالنبضة عشان يظهر
// بالتطبيق: العنوان بيتغيّر كل ما الراوتر يعيد التوزيع، وبلا ما اللوح يقوله،
// إيجاده بيصير مسح شبكة وتخمين.
const char *wifi_sandy_ip(void);
