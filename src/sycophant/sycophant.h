/*
 * wpa_supplicant sycophant relay client
 */

#ifndef SYCOPHANT_H
#define SYCOPHANT_H

#include "utils/includes.h"
#include "utils/common.h"

#define SYCOPHANT_DEFAULT_SOCKET "/run/wpa_sycophant.sock"
#define SYCOPHANT_MAX_IDENTITY 255
#define SYCOPHANT_MSCHAPV2_RESPONSE_LEN 49

int sycophant_set_socket_path(const char *path);
void sycophant_deinit(void);
int sycophant_get_identity(int phase, u8 *identity, size_t identity_size,
			   size_t *identity_len);
int sycophant_get_phase2_identity(const u8 **identity,
				 size_t *identity_len);
int sycophant_has_relayed_response(void);
int sycophant_send_challenge(const u8 *challenge, size_t challenge_len);
int sycophant_wait_response(u8 *response, size_t response_len);

#endif /* SYCOPHANT_H */
