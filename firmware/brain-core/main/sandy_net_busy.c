#include "sandy_net_busy.h"

#include <stdatomic.h>

static atomic_int s_net_owner = NET_OWNER_NONE;

bool net_claim(net_owner_t owner) {
    int expected = NET_OWNER_NONE;
    if (atomic_compare_exchange_strong(&s_net_owner, &expected, (int)owner)) return true;
    return expected == (int)owner;
}

void net_release(net_owner_t owner) {
    int expected = (int)owner;
    atomic_compare_exchange_strong(&s_net_owner, &expected, NET_OWNER_NONE);
}

net_owner_t net_owner(void) {
    return (net_owner_t)atomic_load(&s_net_owner);
}
