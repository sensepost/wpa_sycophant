/*
 * wpa_supplicant sycophant relay client
 */

#include "utils/includes.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>
#include <unistd.h>

#include "utils/common.h"
#include "sycophant.h"

#define SYCOPHANT_HEADER_LEN 6
#define SYCOPHANT_MAX_PAYLOAD 4096

enum sycophant_message {
	SYCOPHANT_GET_IDENTITY_1 = 1,
	SYCOPHANT_GET_IDENTITY_2 = 2,
	SYCOPHANT_PUT_CHALLENGE = 3,
	SYCOPHANT_GET_IDENTITY_1_REPLY = 0x81,
	SYCOPHANT_GET_IDENTITY_2_REPLY = 0x82,
	SYCOPHANT_RESPONSE = 0x84
};

static int sycophant_fd = -1;
static int sycophant_challenge_pending;
static char sycophant_socket_path[sizeof(((struct sockaddr_un *) 0)->sun_path)] =
	SYCOPHANT_DEFAULT_SOCKET;
static u8 sycophant_phase2_identity[SYCOPHANT_MAX_IDENTITY];
static size_t sycophant_phase2_identity_len;
static int sycophant_phase2_identity_valid;
static int sycophant_mschapv2_response_relayed;


static void sycophant_close(void)
{
	if (sycophant_fd >= 0)
		close(sycophant_fd);
	sycophant_fd = -1;
}


int sycophant_set_socket_path(const char *path)
{
	if (!path || !path[0] || os_strlen(path) >= sizeof(sycophant_socket_path))
		return -1;

	os_strlcpy(sycophant_socket_path, path, sizeof(sycophant_socket_path));
	sycophant_close();
	sycophant_challenge_pending = 0;
	sycophant_phase2_identity_len = 0;
	sycophant_phase2_identity_valid = 0;
	sycophant_mschapv2_response_relayed = 0;
	return 0;
}


void sycophant_deinit(void)
{
	sycophant_close();
	sycophant_challenge_pending = 0;
	sycophant_phase2_identity_len = 0;
	sycophant_phase2_identity_valid = 0;
	sycophant_mschapv2_response_relayed = 0;
	os_memset(sycophant_phase2_identity, 0,
		  sizeof(sycophant_phase2_identity));
}


static int sycophant_connect(void)
{
	struct sockaddr_un addr;
	int retry;

	if (sycophant_fd >= 0)
		return 0;

	for (retry = 0; retry < 30; retry++) {
		sycophant_fd = socket(AF_UNIX, SOCK_STREAM, 0);
		if (sycophant_fd < 0)
			return -1;

		os_memset(&addr, 0, sizeof(addr));
		addr.sun_family = AF_UNIX;
		os_strlcpy(addr.sun_path, sycophant_socket_path,
			   sizeof(addr.sun_path));
		if (connect(sycophant_fd, (struct sockaddr *) &addr,
			    sizeof(addr)) == 0) {
			struct timeval timeout;
			timeout.tv_sec = 60;
			timeout.tv_usec = 0;
			setsockopt(sycophant_fd, SOL_SOCKET, SO_RCVTIMEO,
				   &timeout, sizeof(timeout));
#ifdef SO_NOSIGPIPE
			{
				int one = 1;
				setsockopt(sycophant_fd, SOL_SOCKET, SO_NOSIGPIPE,
					   &one, sizeof(one));
			}
#endif /* SO_NOSIGPIPE */
			return 0;
		}

		sycophant_close();
		usleep(100000);
	}

	wpa_printf(MSG_ERROR, "SYCOPHANT: Could not connect to Mana socket %s",
		   sycophant_socket_path);
	return -1;
}


static int sycophant_write_all(const u8 *data, size_t len)
{
	while (len) {
		ssize_t res;

#ifdef MSG_NOSIGNAL
		res = send(sycophant_fd, data, len, MSG_NOSIGNAL);
#else
		res = send(sycophant_fd, data, len, 0);
#endif
		if (res < 0 && errno == EINTR)
			continue;
		if (res <= 0)
			return -1;
		data += res;
		len -= res;
	}
	return 0;
}


static int sycophant_read_all(u8 *data, size_t len)
{
	while (len) {
		ssize_t res = recv(sycophant_fd, data, len, 0);

		if (res < 0 && errno == EINTR)
			continue;
		if (res <= 0)
			return -1;
		data += res;
		len -= res;
	}
	return 0;
}


static int sycophant_send_frame(u8 type, const u8 *payload, size_t len)
{
	u8 header[SYCOPHANT_HEADER_LEN];

	if (len > SYCOPHANT_MAX_PAYLOAD || len > 0xffff ||
	    sycophant_connect() < 0)
		return -1;
	header[0] = 'S';
	header[1] = 'Y';
	header[2] = 1;
	header[3] = type;
	WPA_PUT_BE16(header + 4, len);
	if (sycophant_write_all(header, sizeof(header)) < 0 ||
	    (len && sycophant_write_all(payload, len) < 0)) {
		sycophant_close();
		return -1;
	}
	return 0;
}


static int sycophant_read_frame(u8 *type, u8 *payload, size_t payload_size,
				size_t *payload_len)
{
	u8 header[SYCOPHANT_HEADER_LEN];
	size_t len;

	if (sycophant_read_all(header, sizeof(header)) < 0 ||
	    header[0] != 'S' || header[1] != 'Y' || header[2] != 1) {
		sycophant_close();
		return -1;
	}
	len = WPA_GET_BE16(header + 4);
	if (len > payload_size || len > SYCOPHANT_MAX_PAYLOAD) {
		sycophant_close();
		return -1;
	}
	if (len && sycophant_read_all(payload, len) < 0) {
		sycophant_close();
		return -1;
	}
	*type = header[3];
	*payload_len = len;
	return 0;
}


int sycophant_get_identity(int phase, u8 *identity, size_t identity_size,
			   size_t *identity_len)
{
	u8 type, reply, payload[SYCOPHANT_MAX_PAYLOAD];
	size_t len;

	if (phase != 1 && phase != 2)
		return -1;
	if (phase == 1) {
		sycophant_phase2_identity_len = 0;
		sycophant_phase2_identity_valid = 0;
		sycophant_mschapv2_response_relayed = 0;
	}
	type = phase == 1 ? SYCOPHANT_GET_IDENTITY_1 :
		SYCOPHANT_GET_IDENTITY_2;
	reply = phase == 1 ? SYCOPHANT_GET_IDENTITY_1_REPLY :
		SYCOPHANT_GET_IDENTITY_2_REPLY;
	if (sycophant_send_frame(type, NULL, 0) < 0 ||
	    sycophant_read_frame(&type, payload, sizeof(payload), &len) < 0)
		return -1;
	if (type != reply || len > identity_size) {
		sycophant_close();
		return -1;
	}
	os_memcpy(identity, payload, len);
	*identity_len = len;
	if (phase == 2) {
		os_memcpy(sycophant_phase2_identity, payload, len);
		sycophant_phase2_identity_len = len;
		sycophant_phase2_identity_valid = 1;
	}
	return 0;
}


int sycophant_get_phase2_identity(const u8 **identity, size_t *identity_len)
{
	if (!identity || !identity_len || !sycophant_phase2_identity_valid)
		return -1;
	*identity = sycophant_phase2_identity;
	*identity_len = sycophant_phase2_identity_len;
	return 0;
}


int sycophant_has_relayed_response(void)
{
	return sycophant_mschapv2_response_relayed;
}


int sycophant_send_challenge(const u8 *challenge, size_t challenge_len)
{
	sycophant_mschapv2_response_relayed = 0;
	if (challenge_len != 16 ||
	    sycophant_send_frame(SYCOPHANT_PUT_CHALLENGE, challenge,
				challenge_len) < 0)
		return -1;
	sycophant_challenge_pending = 1;
	return 0;
}


int sycophant_wait_response(u8 *response, size_t response_len)
{
	u8 type;
	size_t len;

	if (!sycophant_challenge_pending)
		return -1;
	sycophant_challenge_pending = 0;
	if (sycophant_connect() < 0 ||
	    sycophant_read_frame(&type, response, response_len, &len) < 0 ||
	    type != SYCOPHANT_RESPONSE || len != response_len) {
		sycophant_close();
		wpa_printf(MSG_ERROR, "SYCOPHANT: Failed to receive relayed response");
		return -1;
	}
	sycophant_mschapv2_response_relayed = 1;
	return 0;
}
