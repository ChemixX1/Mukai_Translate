<?php
/**
 * Plugin Name: Mukai License Server
 * Description: Activates and validates time-limited Mukai Translator licenses.
 * Version: 1.3.0
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if (!defined('ABSPATH')) {
    exit;
}

final class Mukai_License_Server {
    const VERSION = '1.3.0';
    const REST_NAMESPACE = 'mukai-license/v1';
    const PRIVATE_KEY_OPTION = 'mukai_license_private_key';
    const PUBLIC_KEY_OPTION = 'mukai_license_public_key';
    const CODES_TRANSIENT = 'mukai_license_created_codes';
    const UPDATE_OPTION = 'mukai_license_latest_update';
    const GITHUB_REPOSITORY = 'ChemixX1/Mukai-Translator';
    const GITHUB_RELEASE_TRANSIENT = 'mukai_github_latest_release';

    public static function boot() {
        add_action('rest_api_init', array(__CLASS__, 'register_routes'));
        add_action('admin_menu', array(__CLASS__, 'register_admin_page'));
        add_action('admin_post_mukai_license_create', array(__CLASS__, 'handle_create_license'));
        add_action('admin_post_mukai_license_revoke', array(__CLASS__, 'handle_revoke_license'));
        add_action('admin_post_mukai_license_reset_device', array(__CLASS__, 'handle_reset_device'));
        add_action('admin_post_mukai_license_bulk_action', array(__CLASS__, 'handle_bulk_action'));
        add_action('admin_post_mukai_release_publish', array(__CLASS__, 'handle_publish_update'));
        add_action('admin_post_mukai_github_check', array(__CLASS__, 'handle_github_check'));
        add_action('admin_notices', array(__CLASS__, 'render_github_release_notice'));
    }

    public static function activate() {
        global $wpdb;

        $charset_collate = $wpdb->get_charset_collate();
        $licenses = self::licenses_table();
        $devices = self::devices_table();

        require_once ABSPATH . 'wp-admin/includes/upgrade.php';
        dbDelta("CREATE TABLE {$licenses} (
            id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
            license_key_hash varchar(255) NOT NULL,
            code_hint varchar(8) NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'active',
            duration_days smallint(5) unsigned NOT NULL DEFAULT 90,
            max_devices smallint(5) unsigned NOT NULL DEFAULT 1,
            activated_at datetime NULL,
            expires_at datetime NULL,
            created_at datetime NOT NULL,
            updated_at datetime NOT NULL,
            PRIMARY KEY  (id),
            KEY code_hint (code_hint),
            KEY status (status)
        ) {$charset_collate};");

        dbDelta("CREATE TABLE {$devices} (
            id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
            license_id bigint(20) unsigned NOT NULL,
            device_hash char(64) NOT NULL,
            device_name varchar(120) NOT NULL DEFAULT '',
            created_at datetime NOT NULL,
            last_seen_at datetime NOT NULL,
            PRIMARY KEY  (id),
            UNIQUE KEY license_device (license_id, device_hash),
            KEY license_id (license_id)
        ) {$charset_collate};");

        self::ensure_signing_keys();
    }

    private static function licenses_table() {
        global $wpdb;
        return $wpdb->prefix . 'mukai_licenses';
    }

    private static function devices_table() {
        global $wpdb;
        return $wpdb->prefix . 'mukai_license_devices';
    }

    private static function ensure_signing_keys() {
        $private_key = get_option(self::PRIVATE_KEY_OPTION, '');
        $public_key = get_option(self::PUBLIC_KEY_OPTION, '');
        if ($private_key && $public_key) {
            return;
        }
        if (!function_exists('openssl_pkey_new') || !function_exists('openssl_sign')) {
            wp_die('Mukai License Server requires the PHP OpenSSL extension.');
        }

        $keypair = openssl_pkey_new(array(
            'private_key_bits' => 3072,
            'private_key_type' => OPENSSL_KEYTYPE_RSA,
        ));
        if (!$keypair || !openssl_pkey_export($keypair, $private_pem)) {
            wp_die('Mukai License Server could not create its signing key.');
        }
        $details = openssl_pkey_get_details($keypair);
        if (!$details || empty($details['key'])) {
            wp_die('Mukai License Server could not export its public key.');
        }

        update_option(self::PRIVATE_KEY_OPTION, base64_encode($private_pem), false);
        update_option(self::PUBLIC_KEY_OPTION, base64_encode($details['key']), false);
    }

    public static function register_routes() {
        register_rest_route(self::REST_NAMESPACE, '/public-key', array(
            'methods' => WP_REST_Server::READABLE,
            'callback' => array(__CLASS__, 'rest_public_key'),
            'permission_callback' => '__return_true',
        ));
        register_rest_route(self::REST_NAMESPACE, '/activate', array(
            'methods' => WP_REST_Server::CREATABLE,
            'callback' => array(__CLASS__, 'rest_activate'),
            'permission_callback' => '__return_true',
        ));
        register_rest_route(self::REST_NAMESPACE, '/validate', array(
            'methods' => WP_REST_Server::CREATABLE,
            'callback' => array(__CLASS__, 'rest_validate'),
            'permission_callback' => '__return_true',
        ));
        register_rest_route(self::REST_NAMESPACE, '/update', array(
            'methods' => WP_REST_Server::READABLE,
            'callback' => array(__CLASS__, 'rest_update'),
            'permission_callback' => '__return_true',
        ));
    }

    public static function rest_public_key() {
        self::ensure_signing_keys();
        return rest_ensure_response(array(
            'algorithm' => 'RSA-SHA256',
            'public_key' => get_option(self::PUBLIC_KEY_OPTION),
        ));
    }

    public static function rest_update() {
        self::ensure_signing_keys();
        $release = get_option(self::UPDATE_OPTION, array());
        if (!is_array($release) || !self::is_valid_release($release)) {
            return self::rest_error('no_update', 'No Mukai update is currently published.', 404);
        }

        ksort($release, SORT_STRING);
        $message = wp_json_encode($release, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $signature = self::sign_message($message);

        return rest_ensure_response(array(
            'algorithm' => 'RSA-SHA256',
            'release' => $release,
            'signature' => base64_encode($signature),
        ));
    }

    public static function rest_activate(WP_REST_Request $request) {
        $params = $request->get_json_params();
        $code = self::normalise_code(isset($params['code']) ? $params['code'] : '');
        $device_id = isset($params['device_id']) ? (string) $params['device_id'] : '';
        $device_name = isset($params['device_name']) ? sanitize_text_field((string) $params['device_name']) : '';

        if (!$code || !self::is_valid_device_id($device_id)) {
            return self::rest_error('invalid_request', 'Invalid activation code or device identifier.', 400);
        }

        $license = self::find_license_by_code($code);
        if (!$license) {
            return self::rest_error('invalid_license', 'The activation code is not valid.', 403);
        }

        $result = self::allow_device_and_get_license($license, $device_id, $device_name);
        if (is_wp_error($result)) {
            return $result;
        }

        return rest_ensure_response(self::certificate_response($result, $device_id));
    }

    public static function rest_validate(WP_REST_Request $request) {
        $params = $request->get_json_params();
        $license_id = isset($params['license_id']) ? absint($params['license_id']) : 0;
        $device_id = isset($params['device_id']) ? (string) $params['device_id'] : '';
        $device_name = isset($params['device_name']) ? sanitize_text_field((string) $params['device_name']) : '';

        if (!$license_id || !self::is_valid_device_id($device_id)) {
            return self::rest_error('invalid_request', 'Invalid license or device identifier.', 400);
        }

        global $wpdb;
        $license = $wpdb->get_row($wpdb->prepare(
            'SELECT * FROM ' . self::licenses_table() . ' WHERE id = %d',
            $license_id
        ));
        if (!$license || $license->status !== 'active') {
            return self::rest_error('invalid_license', 'The license is not active.', 403);
        }
        if (self::is_expired($license)) {
            self::expire_license($license->id);
            return self::rest_error('expired_license', 'The license has expired.', 403);
        }

        $device_hash = hash('sha256', $device_id);
        $exists = $wpdb->get_var($wpdb->prepare(
            'SELECT id FROM ' . self::devices_table() . ' WHERE license_id = %d AND device_hash = %s',
            $license->id,
            $device_hash
        ));
        if (!$exists) {
            return self::rest_error('unknown_device', 'This device is not registered for the license.', 403);
        }

        $wpdb->update(
            self::devices_table(),
            array('device_name' => substr($device_name, 0, 120), 'last_seen_at' => current_time('mysql', true)),
            array('id' => $exists),
            array('%s', '%s'),
            array('%d')
        );

        return rest_ensure_response(self::certificate_response($license, $device_id));
    }

    private static function find_license_by_code($code) {
        global $wpdb;
        $hint = substr($code, 0, 5);
        $candidates = $wpdb->get_results($wpdb->prepare(
            'SELECT * FROM ' . self::licenses_table() . ' WHERE code_hint = %s',
            $hint
        ));
        foreach ($candidates as $candidate) {
            if (wp_check_password($code, $candidate->license_key_hash)) {
                return $candidate;
            }
        }
        return null;
    }

    private static function allow_device_and_get_license($license, $device_id, $device_name) {
        global $wpdb;
        if ($license->status !== 'active') {
            return self::rest_error('invalid_license', 'The license is not active.', 403);
        }
        if (self::is_expired($license)) {
            self::expire_license($license->id);
            return self::rest_error('expired_license', 'The license has expired.', 403);
        }

        $now = current_time('mysql', true);
        if (!$license->activated_at) {
            $expires_at = gmdate('Y-m-d H:i:s', time() + (DAY_IN_SECONDS * max(1, absint($license->duration_days))));
            $wpdb->update(
                self::licenses_table(),
                array('activated_at' => $now, 'expires_at' => $expires_at, 'updated_at' => $now),
                array('id' => $license->id),
                array('%s', '%s', '%s'),
                array('%d')
            );
            $license = $wpdb->get_row($wpdb->prepare(
                'SELECT * FROM ' . self::licenses_table() . ' WHERE id = %d',
                $license->id
            ));
        }

        $device_hash = hash('sha256', $device_id);
        $devices_table = self::devices_table();
        $device = $wpdb->get_row($wpdb->prepare(
            'SELECT * FROM ' . $devices_table . ' WHERE license_id = %d AND device_hash = %s',
            $license->id,
            $device_hash
        ));
        if (!$device) {
            $device_count = absint($wpdb->get_var($wpdb->prepare(
                'SELECT COUNT(*) FROM ' . $devices_table . ' WHERE license_id = %d',
                $license->id
            )));
            if ($device_count >= max(1, absint($license->max_devices))) {
                return self::rest_error('device_limit', 'This activation code has reached its device limit.', 403);
            }
            $wpdb->insert(
                $devices_table,
                array(
                    'license_id' => $license->id,
                    'device_hash' => $device_hash,
                    'device_name' => substr($device_name, 0, 120),
                    'created_at' => $now,
                    'last_seen_at' => $now,
                ),
                array('%d', '%s', '%s', '%s', '%s')
            );
        } else {
            $wpdb->update(
                $devices_table,
                array('device_name' => substr($device_name, 0, 120), 'last_seen_at' => $now),
                array('id' => $device->id),
                array('%s', '%s'),
                array('%d')
            );
        }

        return $license;
    }

    private static function certificate_response($license, $device_id) {
        $payload = array(
            'device_hash' => hash('sha256', $device_id),
            'expires_at' => $license->expires_at,
            'issued_at' => gmdate('c'),
            'license_id' => absint($license->id),
            'server_time' => gmdate('c'),
            'version' => 1,
        );
        ksort($payload, SORT_STRING);
        $message = wp_json_encode($payload, JSON_UNESCAPED_SLASHES);
        $signature = self::sign_message($message);

        return array(
            'license' => $payload,
            'signature' => base64_encode($signature),
            'algorithm' => 'RSA-SHA256',
        );
    }

    private static function sign_message($message) {
        self::ensure_signing_keys();
        $private_pem = base64_decode(get_option(self::PRIVATE_KEY_OPTION), true);
        $private_key = $private_pem ? openssl_pkey_get_private($private_pem) : false;
        $signature = '';
        if (!$private_key || !openssl_sign($message, $signature, $private_key, OPENSSL_ALGO_SHA256)) {
            wp_die('Mukai License Server could not sign the response.');
        }
        return $signature;
    }

    private static function is_valid_release($release) {
        $required = array('version', 'notes', 'installer_url', 'sha256', 'published_at');
        foreach ($required as $field) {
            if (!isset($release[$field]) || !is_string($release[$field]) || trim($release[$field]) === '') {
                return false;
            }
        }
        return preg_match('/^\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?$/', $release['version'])
            && strpos($release['installer_url'], 'https://') === 0
            && preg_match('/^[a-f0-9]{64}$/', $release['sha256']);
    }

    private static function is_expired($license) {
        return !empty($license->expires_at) && strtotime($license->expires_at . ' UTC') <= time();
    }

    private static function expire_license($license_id) {
        global $wpdb;
        $wpdb->update(
            self::licenses_table(),
            array('status' => 'expired', 'updated_at' => current_time('mysql', true)),
            array('id' => $license_id),
            array('%s', '%s'),
            array('%d')
        );
    }

    private static function normalise_code($code) {
        $code = strtoupper(preg_replace('/[^A-Z0-9]/', '', (string) $code));
        return strlen($code) === 25 ? $code : '';
    }

    private static function is_valid_device_id($device_id) {
        return is_string($device_id) && (bool) preg_match('/^[A-Za-z0-9_-]{32,256}$/', $device_id);
    }

    private static function rest_error($code, $message, $status) {
        return new WP_Error($code, $message, array('status' => $status));
    }

    public static function register_admin_page() {
        add_menu_page(
            'Mukai Control',
            'Mukai Control',
            'manage_options',
            'mukai-licenses',
            array(__CLASS__, 'render_control_panel'),
            'dashicons-shield-alt',
            58
        );
    }

    public static function render_admin_page() {
        if (!current_user_can('manage_options')) {
            return;
        }
        self::ensure_signing_keys();
        global $wpdb;
        $licenses = $wpdb->get_results('SELECT * FROM ' . self::licenses_table() . ' ORDER BY id DESC LIMIT 100');
        $created_codes = get_transient(self::CODES_TRANSIENT . '_' . get_current_user_id());
        delete_transient(self::CODES_TRANSIENT . '_' . get_current_user_id());
        ?>
        <div class="wrap">
            <h1>Mukai Licenses</h1>
            <p>Los códigos duran 90 días desde la primera activación. Guárdalos al crearlos: por seguridad no se almacenan en texto plano.</p>
            <?php if ($created_codes) : ?>
                <div class="notice notice-success"><p><strong>Código creado:</strong> <code><?php echo esc_html($created_codes); ?></code></p></div>
            <?php endif; ?>
            <h2>Crear código</h2>
            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
                <?php wp_nonce_field('mukai_license_create'); ?>
                <input type="hidden" name="action" value="mukai_license_create">
                <label>Equipos permitidos <input type="number" name="max_devices" min="1" max="10" value="1"></label>
                <button type="submit" class="button button-primary">Crear código de 90 días</button>
            </form>
            <h2>Clave pública de la aplicación</h2>
            <p>Copia este valor al configurar la compilación de Mukai Translator. Nunca compartas la clave privada del servidor.</p>
            <textarea readonly rows="3" class="large-text code"><?php echo esc_textarea(get_option(self::PUBLIC_KEY_OPTION)); ?></textarea>
            <p>Endpoint: <code><?php echo esc_html(rest_url(self::REST_NAMESPACE)); ?></code></p>
            <?php $current_update = get_option(self::UPDATE_OPTION, array()); ?>
            <h2>Publicar actualizacion de Mukai</h2>
            <p>Sube primero el instalador <code>.exe</code> a tu hosting. Esta ficha publica una nota firmada que la aplicacion verifica antes de descargarlo.</p>
            <?php if (isset($_GET['mukai_release_published'])) : ?>
                <div class="notice notice-success"><p>Actualizacion publicada correctamente.</p></div>
            <?php endif; ?>
            <?php if (is_array($current_update) && self::is_valid_release($current_update)) : ?>
                <p><strong>Version publicada:</strong> <code><?php echo esc_html($current_update['version']); ?></code> &mdash; <a href="<?php echo esc_url($current_update['installer_url']); ?>" target="_blank" rel="noopener">ver instalador</a></p>
            <?php endif; ?>
            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
                <?php wp_nonce_field('mukai_release_publish'); ?>
                <input type="hidden" name="action" value="mukai_release_publish">
                <p><label>Version <input required pattern="[0-9]+(\.[0-9]+){1,3}([+-][0-9A-Za-z.-]+)?" name="version" value="<?php echo esc_attr(is_array($current_update) && isset($current_update['version']) ? $current_update['version'] : ''); ?>" placeholder="1.0.1"></label></p>
                <p><label>URL HTTPS del instalador<br><input required type="url" class="large-text code" name="installer_url" value="<?php echo esc_attr(is_array($current_update) && isset($current_update['installer_url']) ? $current_update['installer_url'] : ''); ?>" placeholder="https://tu-dominio.com/downloads/MukaiTranslator-Setup-1.0.1.exe"></label></p>
                <p><label>SHA-256 del instalador<br><input required pattern="[A-Fa-f0-9]{64}" maxlength="64" class="large-text code" name="sha256" value="<?php echo esc_attr(is_array($current_update) && isset($current_update['sha256']) ? $current_update['sha256'] : ''); ?>"></label></p>
                <p><label>Novedades (se muestran antes de descargar)<br><textarea required rows="6" class="large-text" name="notes"><?php echo esc_textarea(is_array($current_update) && isset($current_update['notes']) ? $current_update['notes'] : ''); ?></textarea></label></p>
                <button type="submit" class="button button-primary">Publicar actualizacion</button>
            </form>
            <h2>Licencias</h2>
            <table class="widefat striped">
                <thead><tr><th>ID</th><th>Pista</th><th>Estado</th><th>Vence</th><th>Equipos</th><th>Acciones</th></tr></thead>
                <tbody>
                <?php foreach ($licenses as $license) : ?>
                    <?php $device_count = absint($wpdb->get_var($wpdb->prepare('SELECT COUNT(*) FROM ' . self::devices_table() . ' WHERE license_id = %d', $license->id))); ?>
                    <tr>
                        <td><?php echo esc_html($license->id); ?></td>
                        <td><code><?php echo esc_html($license->code_hint); ?>…</code></td>
                        <td><?php echo esc_html($license->status); ?></td>
                        <td><?php echo esc_html($license->expires_at ? get_date_from_gmt($license->expires_at) : 'Sin activar'); ?></td>
                        <td><?php echo esc_html($device_count . ' / ' . $license->max_devices); ?></td>
                        <td>
                            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>" style="display:inline">
                                <?php wp_nonce_field('mukai_license_revoke_' . $license->id); ?>
                                <input type="hidden" name="action" value="mukai_license_revoke"><input type="hidden" name="license_id" value="<?php echo esc_attr($license->id); ?>">
                                <button class="button" type="submit">Revocar</button>
                            </form>
                            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>" style="display:inline">
                                <?php wp_nonce_field('mukai_license_reset_' . $license->id); ?>
                                <input type="hidden" name="action" value="mukai_license_reset_device"><input type="hidden" name="license_id" value="<?php echo esc_attr($license->id); ?>">
                                <button class="button" type="submit">Liberar equipos</button>
                            </form>
                        </td>
                    </tr>
                <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <?php
    }

    private static function refresh_expired_licenses() {
        global $wpdb;
        $now = current_time('mysql', true);
        $wpdb->query($wpdb->prepare(
            'UPDATE ' . self::licenses_table() . " SET status = 'expired', updated_at = %s WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= %s",
            $now,
            $now
        ));
    }

    private static function get_dashboard_stats() {
        global $wpdb;
        $stats = $wpdb->get_row(
            "SELECT COUNT(*) AS total,
                SUM(CASE WHEN status = 'active' AND activated_at IS NULL THEN 1 ELSE 0 END) AS available,
                SUM(CASE WHEN status = 'active' AND activated_at IS NOT NULL THEN 1 ELSE 0 END) AS in_use,
                SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) AS expired,
                SUM(CASE WHEN status = 'revoked' THEN 1 ELSE 0 END) AS revoked
             FROM " . self::licenses_table(),
            ARRAY_A
        );
        $stats = is_array($stats) ? $stats : array();
        foreach (array('total', 'available', 'in_use', 'expired', 'revoked') as $key) {
            $stats[$key] = isset($stats[$key]) ? absint($stats[$key]) : 0;
        }
        $stats['devices'] = absint($wpdb->get_var('SELECT COUNT(*) FROM ' . self::devices_table()));
        return $stats;
    }

    private static function get_filtered_licenses($status, $search, $page, $per_page) {
        global $wpdb;
        $where = array('1=1');
        $params = array();

        if (in_array($status, array('active', 'available', 'in_use', 'expired', 'revoked'), true)) {
            if ($status === 'available') {
                $where[] = "l.status = 'active' AND l.activated_at IS NULL";
            } elseif ($status === 'in_use') {
                $where[] = "l.status = 'active' AND l.activated_at IS NOT NULL";
            } else {
                $where[] = 'l.status = %s';
                $params[] = $status;
            }
        }

        if ($search !== '') {
            $like = '%' . $wpdb->esc_like(strtoupper($search)) . '%';
            if (ctype_digit($search)) {
                $where[] = '(l.code_hint LIKE %s OR l.id = %d)';
                $params[] = $like;
                $params[] = absint($search);
            } else {
                $where[] = 'l.code_hint LIKE %s';
                $params[] = $like;
            }
        }

        $where_sql = ' WHERE ' . implode(' AND ', $where);
        $count_sql = 'SELECT COUNT(*) FROM ' . self::licenses_table() . ' l' . $where_sql;
        $total = $params
            ? absint($wpdb->get_var($wpdb->prepare($count_sql, $params)))
            : absint($wpdb->get_var($count_sql));

        $offset = max(0, ($page - 1) * $per_page);
        $query_params = array_merge($params, array($per_page, $offset));
        $sql = 'SELECT l.*, COUNT(d.id) AS device_count, MAX(d.last_seen_at) AS last_seen_at
                FROM ' . self::licenses_table() . ' l
                LEFT JOIN ' . self::devices_table() . ' d ON d.license_id = l.id'
                . $where_sql . '
                GROUP BY l.id
                ORDER BY l.id DESC
                LIMIT %d OFFSET %d';
        return array($wpdb->get_results($wpdb->prepare($sql, $query_params)), $total);
    }

    private static function license_display_status($license) {
        if ($license->status === 'active' && empty($license->activated_at)) {
            return array('Disponible', 'available');
        }
        $labels = array(
            'active' => array('Activa', 'active'),
            'expired' => array('Vencida', 'expired'),
            'revoked' => array('Revocada', 'revoked'),
        );
        return isset($labels[$license->status]) ? $labels[$license->status] : array(ucfirst($license->status), 'neutral');
    }

    private static function admin_tab_url($tab, $extra = array()) {
        return add_query_arg(array_merge(array('page' => 'mukai-licenses', 'tab' => $tab), $extra), admin_url('admin.php'));
    }

    private static function get_latest_github_release($force = false) {
        if (!$force) {
            $cached = get_transient(self::GITHUB_RELEASE_TRANSIENT);
            if (is_array($cached)) {
                return $cached;
            }
        }

        $empty = array(
            'version' => '',
            'notes' => '',
            'installer_url' => '',
            'sha256' => '',
            'html_url' => 'https://github.com/' . self::GITHUB_REPOSITORY . '/releases',
            'asset_name' => '',
            'published_at' => '',
            'error' => '',
            'checked_at' => gmdate('c'),
        );
        $url = 'https://api.github.com/repos/' . self::GITHUB_REPOSITORY . '/releases/latest';
        $response = wp_remote_get($url, array(
            'timeout' => 10,
            'redirection' => 3,
            'headers' => array(
                'Accept' => 'application/vnd.github+json',
                'User-Agent' => 'Mukai-License-Server/' . self::VERSION,
                'X-GitHub-Api-Version' => '2022-11-28',
            ),
        ));

        if (is_wp_error($response)) {
            $empty['error'] = 'No se pudo conectar con GitHub: ' . $response->get_error_message();
            set_transient(self::GITHUB_RELEASE_TRANSIENT, $empty, MINUTE_IN_SECONDS * 15);
            return $empty;
        }

        $status_code = absint(wp_remote_retrieve_response_code($response));
        if ($status_code === 404) {
            $empty['error'] = 'El repositorio todavía no tiene una versión publicada en GitHub Releases.';
            set_transient(self::GITHUB_RELEASE_TRANSIENT, $empty, HOUR_IN_SECONDS);
            return $empty;
        }
        if ($status_code !== 200) {
            $empty['error'] = 'GitHub respondió con el código HTTP ' . $status_code . '.';
            set_transient(self::GITHUB_RELEASE_TRANSIENT, $empty, MINUTE_IN_SECONDS * 15);
            return $empty;
        }

        $payload = json_decode(wp_remote_retrieve_body($response), true);
        if (!is_array($payload) || empty($payload['tag_name'])) {
            $empty['error'] = 'GitHub devolvió una versión sin datos válidos.';
            set_transient(self::GITHUB_RELEASE_TRANSIENT, $empty, MINUTE_IN_SECONDS * 15);
            return $empty;
        }

        $version = trim(preg_replace('/^[vV]/', '', sanitize_text_field($payload['tag_name'])));
        if (!preg_match('/^[0-9]+(?:\.[0-9]+){1,3}(?:[+-][0-9A-Za-z.-]+)?$/', $version)) {
            $empty['error'] = 'La etiqueta de GitHub no contiene una versión compatible.';
            set_transient(self::GITHUB_RELEASE_TRANSIENT, $empty, HOUR_IN_SECONDS);
            return $empty;
        }

        $result = $empty;
        $result['version'] = $version;
        $result['notes'] = isset($payload['body']) ? trim(sanitize_textarea_field($payload['body'])) : '';
        $result['html_url'] = isset($payload['html_url']) ? esc_url_raw($payload['html_url']) : $empty['html_url'];
        $result['published_at'] = isset($payload['published_at']) ? sanitize_text_field($payload['published_at']) : '';

        $preferred_name = 'MukaiTranslator-Setup-' . $version . '.exe';
        $fallback_asset = null;
        foreach ((array) (isset($payload['assets']) ? $payload['assets'] : array()) as $asset) {
            if (!is_array($asset) || empty($asset['name']) || empty($asset['browser_download_url'])) {
                continue;
            }
            $asset_name = sanitize_file_name($asset['name']);
            if (!preg_match('/\.exe$/i', $asset_name)) {
                continue;
            }
            if ($fallback_asset === null) {
                $fallback_asset = $asset;
            }
            if (strcasecmp($asset_name, $preferred_name) === 0) {
                $fallback_asset = $asset;
                break;
            }
        }

        if (is_array($fallback_asset)) {
            $result['asset_name'] = sanitize_file_name($fallback_asset['name']);
            $result['installer_url'] = esc_url_raw($fallback_asset['browser_download_url']);
            $digest = isset($fallback_asset['digest']) ? trim((string) $fallback_asset['digest']) : '';
            if (preg_match('/^sha256:([a-fA-F0-9]{64})$/', $digest, $matches)) {
                $result['sha256'] = strtolower($matches[1]);
            }
        }

        set_transient(self::GITHUB_RELEASE_TRANSIENT, $result, HOUR_IN_SECONDS * 4);
        return $result;
    }

    private static function github_release_is_importable($release) {
        return is_array($release)
            && !empty($release['version'])
            && !empty($release['notes'])
            && !empty($release['installer_url'])
            && preg_match('/^[a-f0-9]{64}$/', isset($release['sha256']) ? $release['sha256'] : '');
    }

    private static function github_release_is_newer($release, $current_update) {
        $current_version = is_array($current_update) && !empty($current_update['version']) ? $current_update['version'] : '0.0.0';
        return !empty($release['version']) && version_compare($release['version'], $current_version, '>');
    }

    public static function render_github_release_notice() {
        if (!current_user_can('manage_options')) {
            return;
        }
        $release = self::get_latest_github_release(false);
        $current_update = get_option(self::UPDATE_OPTION, array());
        if (!self::github_release_is_newer($release, $current_update)) {
            return;
        }
        $url = self::admin_tab_url('updates', array('github_import' => '1'));
        ?>
        <div class="notice notice-warning"><p><strong>Nueva versión de Mukai Translator en GitHub: <?php echo esc_html($release['version']); ?>.</strong> Revísala antes de publicarla para los usuarios.</p><p><a class="button button-primary" href="<?php echo esc_url($url); ?>">Revisar actualización</a> <a class="button" target="_blank" rel="noopener" href="<?php echo esc_url($release['html_url']); ?>">Abrir GitHub Release</a></p></div>
        <?php
    }

    public static function render_control_panel() {
        if (!current_user_can('manage_options')) {
            return;
        }
        self::ensure_signing_keys();
        self::refresh_expired_licenses();

        $tab = isset($_GET['tab']) ? sanitize_key(wp_unslash($_GET['tab'])) : 'licenses';
        if (!in_array($tab, array('licenses', 'updates', 'security'), true)) {
            $tab = 'licenses';
        }
        $stats = self::get_dashboard_stats();
        $created_codes = get_transient(self::CODES_TRANSIENT . '_' . get_current_user_id());
        delete_transient(self::CODES_TRANSIENT . '_' . get_current_user_id());
        if ($created_codes && !is_array($created_codes)) {
            $created_codes = array($created_codes);
        }
        $current_update = get_option(self::UPDATE_OPTION, array());
        ?>
        <style>
            .mukai-wrap{max-width:1500px;margin-top:20px;color:#22232a}.mukai-header{display:flex;align-items:center;gap:14px;margin-bottom:18px}.mukai-mark{width:46px;height:46px;border-radius:13px;background:#d13655;color:#fff;display:grid;place-items:center;font-weight:800;font-size:20px;box-shadow:0 8px 22px rgba(209,54,85,.22)}.mukai-header h1{margin:0;font-size:27px;font-weight:750}.mukai-header p{margin:3px 0 0;color:#666b76}.mukai-tabs{display:flex;gap:6px;border-bottom:1px solid #d8dae0;margin-bottom:18px}.mukai-tab{text-decoration:none;color:#555a64;padding:10px 15px;font-weight:650;border-bottom:3px solid transparent}.mukai-tab:hover{color:#d13655}.mukai-tab.active{color:#d13655;border-color:#d13655}.mukai-cards{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));gap:12px;margin:16px 0}.mukai-card,.mukai-panel{background:#fff;border:1px solid #dedfe4;border-radius:12px;box-shadow:0 2px 8px rgba(25,25,35,.035)}.mukai-card{padding:16px;border-top:3px solid #d13655}.mukai-card span{display:block;color:#717680;font-size:12px;text-transform:uppercase;letter-spacing:.04em}.mukai-card strong{display:block;margin-top:5px;font-size:25px;color:#202129}.mukai-grid{display:grid;grid-template-columns:minmax(300px,380px) minmax(0,1fr);gap:16px;align-items:start}.mukai-panel{padding:20px;margin-bottom:16px}.mukai-panel h2{margin:0 0 5px;font-size:18px}.mukai-panel .description{margin:0 0 16px;color:#6d727c}.mukai-field{margin-bottom:13px}.mukai-field label{display:block;font-weight:650;margin-bottom:5px}.mukai-field input,.mukai-field select,.mukai-field textarea{width:100%;max-width:none}.mukai-created{background:#fff7f9;border-color:#ef9caf}.mukai-created textarea{min-height:130px;font:600 14px/1.6 Consolas,monospace}.mukai-toolbar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}.mukai-filter,.mukai-bulk{display:flex;flex-wrap:wrap;gap:7px;align-items:center}.mukai-filter input[type=search]{min-width:220px}.mukai-table-wrap{overflow:auto;border:1px solid #e0e1e5;border-radius:10px}.mukai-table{border:0;box-shadow:none}.mukai-table th{background:#f7f7f9;font-weight:700}.mukai-table td{vertical-align:middle}.mukai-hint{font:700 13px Consolas,monospace;letter-spacing:.06em}.mukai-badge{display:inline-flex;align-items:center;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:700}.mukai-badge.active{color:#087642;background:#e5f7ee}.mukai-badge.available{color:#245eb4;background:#eaf1ff}.mukai-badge.expired{color:#9a6200;background:#fff2d6}.mukai-badge.revoked{color:#a1263d;background:#fde9ed}.mukai-actions{display:flex;flex-wrap:wrap;gap:5px;min-width:225px}.mukai-action{min-height:29px!important;line-height:27px!important;padding:0 9px!important}.mukai-danger{color:#b4233d!important;border-color:#e5a1ae!important}.mukai-update-state{display:flex;gap:12px;align-items:center;padding:14px;background:#f7f8fa;border-radius:9px;margin-bottom:18px}.mukai-update-state .dashicons{color:#20a15f;font-size:28px;width:28px;height:28px}.mukai-copy-row{display:flex;align-items:center;gap:8px}.mukai-copy-row input{flex:1}.mukai-empty{text-align:center;padding:36px!important;color:#747985}@media(max-width:1100px){.mukai-cards{grid-template-columns:repeat(3,1fr)}.mukai-grid{grid-template-columns:1fr}}@media(max-width:700px){.mukai-cards{grid-template-columns:repeat(2,1fr)}.mukai-toolbar{align-items:flex-start}}
        </style>
        <div class="wrap mukai-wrap">
            <div class="mukai-header"><div class="mukai-mark">MT</div><div><h1>Mukai Control</h1><p>Licencias, equipos y actualizaciones de Mukai Translator.</p></div></div>
            <nav class="mukai-tabs">
                <a class="mukai-tab <?php echo $tab === 'licenses' ? 'active' : ''; ?>" href="<?php echo esc_url(self::admin_tab_url('licenses')); ?>">Licencias</a>
                <a class="mukai-tab <?php echo $tab === 'updates' ? 'active' : ''; ?>" href="<?php echo esc_url(self::admin_tab_url('updates')); ?>">Actualizaciones</a>
                <a class="mukai-tab <?php echo $tab === 'security' ? 'active' : ''; ?>" href="<?php echo esc_url(self::admin_tab_url('security')); ?>">Conexión y seguridad</a>
            </nav>
            <?php if (isset($_GET['mukai_action_done'])) : ?><div class="notice notice-success is-dismissible"><p><?php echo esc_html(absint($_GET['mukai_action_done'])); ?> licencia(s) actualizada(s).</p></div><?php endif; ?>
            <?php if ($tab === 'licenses') self::render_licenses_tab($stats, $created_codes); ?>
            <?php if ($tab === 'updates') self::render_updates_tab($current_update); ?>
            <?php if ($tab === 'security') self::render_security_tab(); ?>
        </div>
        <script>
        (function(){document.querySelectorAll('[data-mukai-copy]').forEach(function(b){b.addEventListener('click',function(){var t=document.getElementById(b.getAttribute('data-mukai-copy'));if(!t)return;t.select();var d=function(){b.textContent='Copiado';setTimeout(function(){b.textContent='Copiar'},1400)};if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(t.value).then(d);else{document.execCommand('copy');d()}})});var a=document.getElementById('mukai-select-all');if(a)a.addEventListener('change',function(){document.querySelectorAll('.mukai-license-check').forEach(function(c){c.checked=a.checked})});document.querySelectorAll('[data-mukai-confirm]').forEach(function(f){f.addEventListener('submit',function(e){if(!window.confirm(f.getAttribute('data-mukai-confirm')))e.preventDefault()})})}());
        </script>
        <?php
    }

    private static function render_licenses_tab($stats, $created_codes) {
        $status = isset($_GET['license_status']) ? sanitize_key(wp_unslash($_GET['license_status'])) : '';
        $search = isset($_GET['s']) ? sanitize_text_field(wp_unslash($_GET['s'])) : '';
        $page = isset($_GET['license_page']) ? max(1, absint($_GET['license_page'])) : 1;
        $per_page = 25;
        list($licenses, $total) = self::get_filtered_licenses($status, $search, $page, $per_page);
        $total_pages = max(1, (int) ceil($total / $per_page));
        ?>
        <div class="mukai-cards">
            <div class="mukai-card"><span>Total</span><strong><?php echo esc_html($stats['total']); ?></strong></div><div class="mukai-card"><span>Disponibles</span><strong><?php echo esc_html($stats['available']); ?></strong></div><div class="mukai-card"><span>En uso</span><strong><?php echo esc_html($stats['in_use']); ?></strong></div><div class="mukai-card"><span>Vencidas</span><strong><?php echo esc_html($stats['expired']); ?></strong></div><div class="mukai-card"><span>Revocadas</span><strong><?php echo esc_html($stats['revoked']); ?></strong></div><div class="mukai-card"><span>Equipos</span><strong><?php echo esc_html($stats['devices']); ?></strong></div>
        </div>
        <div class="mukai-grid"><div>
            <section class="mukai-panel"><h2>Crear licencias</h2><p class="description">La vigencia comienza en la primera activación. Los códigos completos se muestran una sola vez.</p>
                <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>"><?php wp_nonce_field('mukai_license_create'); ?><input type="hidden" name="action" value="mukai_license_create">
                    <div class="mukai-field"><label>Cantidad</label><input type="number" name="quantity" min="1" max="50" value="1"></div>
                    <div class="mukai-field"><label>Duración desde la activación</label><select name="duration_days"><option value="30">30 días</option><option value="90" selected>90 días</option><option value="180">180 días</option><option value="365">365 días</option></select></div>
                    <div class="mukai-field"><label>Equipos permitidos por licencia</label><input type="number" name="max_devices" min="1" max="10" value="1"></div>
                    <button type="submit" class="button button-primary button-large">Generar códigos</button>
                </form>
            </section>
            <?php if ($created_codes) : ?><section class="mukai-panel mukai-created"><h2>Códigos recién creados</h2><p class="description">Cópialos ahora. Por seguridad, después solo se conserva su hash.</p><textarea id="mukai-created-codes" readonly><?php echo esc_textarea(implode("\n", $created_codes)); ?></textarea><p><button type="button" class="button button-primary" data-mukai-copy="mukai-created-codes">Copiar</button></p></section><?php endif; ?>
        </div><section class="mukai-panel">
            <div class="mukai-toolbar"><form class="mukai-filter" method="get"><input type="hidden" name="page" value="mukai-licenses"><input type="hidden" name="tab" value="licenses"><input type="search" name="s" value="<?php echo esc_attr($search); ?>" placeholder="Buscar por ID o inicio del código"><select name="license_status"><option value="">Todos los estados</option><option value="available" <?php selected($status, 'available'); ?>>Disponibles</option><option value="in_use" <?php selected($status, 'in_use'); ?>>En uso</option><option value="expired" <?php selected($status, 'expired'); ?>>Vencidas</option><option value="revoked" <?php selected($status, 'revoked'); ?>>Revocadas</option></select><button class="button">Filtrar</button><?php if ($status || $search) : ?><a class="button" href="<?php echo esc_url(self::admin_tab_url('licenses')); ?>">Limpiar</a><?php endif; ?></form><span><strong><?php echo esc_html($total); ?></strong> resultado(s)</span></div>
            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>" data-mukai-confirm="¿Aplicar esta acción a las licencias seleccionadas?"><?php wp_nonce_field('mukai_license_bulk_action'); ?><input type="hidden" name="action" value="mukai_license_bulk_action"><div class="mukai-bulk"><select name="bulk_operation"><option value="">Acción masiva</option><option value="revoke">Revocar</option><option value="reactivate">Reactivar</option><option value="extend_90">Añadir 90 días</option><option value="reset_devices">Liberar equipos</option></select><button class="button">Aplicar</button></div>
                <div class="mukai-table-wrap"><table class="widefat striped mukai-table"><thead><tr><td class="check-column"><input id="mukai-select-all" type="checkbox"></td><th>ID / código</th><th>Estado</th><th>Activación</th><th>Vencimiento</th><th>Equipos</th><th>Última conexión</th><th>Acciones rápidas</th></tr></thead><tbody>
                    <?php if (!$licenses) : ?><tr><td colspan="8" class="mukai-empty">No hay licencias que coincidan con el filtro.</td></tr><?php endif; ?>
                    <?php foreach ($licenses as $license) : ?><?php list($status_label, $status_class) = self::license_display_status($license); ?><tr>
                        <th class="check-column"><input class="mukai-license-check" type="checkbox" name="license_ids[]" value="<?php echo esc_attr($license->id); ?>"></th><td><strong>#<?php echo esc_html($license->id); ?></strong><br><span class="mukai-hint"><?php echo esc_html($license->code_hint); ?>…</span></td><td><span class="mukai-badge <?php echo esc_attr($status_class); ?>"><?php echo esc_html($status_label); ?></span></td><td><?php echo esc_html($license->activated_at ? get_date_from_gmt($license->activated_at, 'd/m/Y H:i') : 'Sin activar'); ?></td>
                        <td><?php if ($license->expires_at) : ?><?php $days_left = (int) ceil((strtotime($license->expires_at . ' UTC') - time()) / DAY_IN_SECONDS); ?><?php echo esc_html(get_date_from_gmt($license->expires_at, 'd/m/Y H:i')); ?><br><small><?php echo $days_left > 0 ? esc_html($days_left . ' día(s)') : 'Finalizada'; ?></small><?php else : ?>Empieza al activar<?php endif; ?></td><td><strong><?php echo esc_html(absint($license->device_count)); ?></strong> / <?php echo esc_html($license->max_devices); ?></td><td><?php echo esc_html($license->last_seen_at ? get_date_from_gmt($license->last_seen_at, 'd/m/Y H:i') : '—'); ?></td>
                        <td><div class="mukai-actions"><?php if ($license->status === 'active') self::render_quick_action($license->id, 'revoke', 'Revocar', true); ?><?php if ($license->status === 'revoked') self::render_quick_action($license->id, 'reactivate', 'Reactivar'); ?><?php if ($license->status === 'expired') self::render_quick_action($license->id, 'extend_90', 'Renovar 90 días'); ?><?php if ($license->activated_at && $license->status !== 'expired') self::render_quick_action($license->id, 'extend_90', '+90 días'); ?><?php if (absint($license->device_count) > 0) self::render_quick_action($license->id, 'reset_devices', 'Liberar equipos'); ?></div></td>
                    </tr><?php endforeach; ?>
                </tbody></table></div>
            </form>
            <?php if ($total_pages > 1) : ?><div class="tablenav"><div class="tablenav-pages"><?php echo wp_kses_post(paginate_links(array('base' => add_query_arg('license_page', '%#%'), 'format' => '', 'current' => $page, 'total' => $total_pages))); ?></div></div><?php endif; ?>
        </section></div>
        <?php
    }

    private static function render_quick_action($license_id, $operation, $label, $danger = false) {
        ?><button type="submit" name="quick_action" value="<?php echo esc_attr($operation . ':' . absint($license_id)); ?>" class="button mukai-action <?php echo $danger ? 'mukai-danger' : ''; ?>"><?php echo esc_html($label); ?></button><?php
    }

    private static function render_updates_tab($current_update) {
        $has_update = is_array($current_update) && self::is_valid_release($current_update);
        $github_release = self::get_latest_github_release(false);
        $github_importable = self::github_release_is_importable($github_release);
        $github_newer = self::github_release_is_newer($github_release, $current_update);
        $import_github = isset($_GET['github_import']) && $_GET['github_import'] === '1' && $github_importable;
        $form_release = $import_github ? $github_release : ($has_update ? $current_update : array());
        ?>
        <section class="mukai-panel"><h2>Canal de actualizaciones</h2><p class="description">Publica el instalador que recibirán las aplicaciones. El manifiesto se firma automáticamente.</p><div class="mukai-update-state"><span class="dashicons dashicons-yes-alt"></span><div><strong><?php echo $has_update ? 'Versión ' . esc_html($current_update['version']) . ' publicada' : 'Canal listo, sin versión publicada'; ?></strong><br><?php if ($has_update) : ?><a href="<?php echo esc_url($current_update['installer_url']); ?>" target="_blank" rel="noopener">Abrir instalador actual</a> · Publicada <?php echo esc_html($current_update['published_at']); ?><?php else : ?>Configura la primera versión debajo.<?php endif; ?></div></div>
        <?php if (isset($_GET['mukai_release_published'])) : ?><div class="notice notice-success inline"><p>Actualización publicada correctamente.</p></div><?php endif; ?>
        </section>

        <section class="mukai-panel"><h2>GitHub Releases</h2><p class="description">WordPress revisa el repositorio público <code><?php echo esc_html(self::GITHUB_REPOSITORY); ?></code> cada cuatro horas y muestra un aviso cuando existe una versión superior.</p>
            <?php if (!empty($github_release['error'])) : ?><div class="notice notice-info inline"><p><?php echo esc_html($github_release['error']); ?></p></div><?php elseif ($github_newer) : ?><div class="notice notice-warning inline"><p><strong>GitHub tiene la versión <?php echo esc_html($github_release['version']); ?> pendiente de publicación.</strong><?php if (!$github_importable) : ?> El release debe incluir el instalador EXE con su digest SHA-256.<?php endif; ?></p></div><?php elseif (!empty($github_release['version'])) : ?><div class="notice notice-success inline"><p>GitHub y el canal público están sincronizados en la versión <?php echo esc_html($github_release['version']); ?>.</p></div><?php endif; ?>
            <div style="display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin:14px 0"><form style="display:inline;margin:0" method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>"><?php wp_nonce_field('mukai_github_check'); ?><input type="hidden" name="action" value="mukai_github_check"><button class="button" type="submit">Revisar GitHub ahora</button></form><a class="button" target="_blank" rel="noopener" href="<?php echo esc_url($github_release['html_url']); ?>">Abrir releases</a><?php if ($github_newer && $github_importable) : ?><a class="button button-primary" href="<?php echo esc_url(self::admin_tab_url('updates', array('github_import' => '1'))); ?>">Preparar versión <?php echo esc_html($github_release['version']); ?></a><?php endif; ?></div>
            <?php if (isset($_GET['mukai_github_checked'])) : ?><p><small>Última consulta: <?php echo esc_html($github_release['checked_at']); ?></small></p><?php endif; ?>
        </section>

        <section class="mukai-panel"><h2><?php echo $import_github ? 'Revisar y publicar desde GitHub' : 'Publicación manual'; ?></h2><p class="description"><?php echo $import_github ? 'Verifica los datos importados. La actualización solo llegará a los usuarios después de pulsar el botón de publicación.' : 'También puedes introducir manualmente un instalador alojado mediante HTTPS.'; ?></p>
        <?php if ($import_github) : ?><div class="notice notice-warning inline"><p>Confirma las notas, la versión y el instalador antes de firmar. WordPress no publica automáticamente contenido de GitHub.</p></div><?php endif; ?>
        <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>"><?php wp_nonce_field('mukai_release_publish'); ?><input type="hidden" name="action" value="mukai_release_publish"><div class="mukai-field"><label>Versión</label><input required pattern="[0-9]+(\.[0-9]+){1,3}([+-][0-9A-Za-z.-]+)?" name="version" value="<?php echo esc_attr(isset($form_release['version']) ? $form_release['version'] : ''); ?>" placeholder="1.0.2"></div><div class="mukai-field"><label>URL HTTPS del instalador</label><input required type="url" name="installer_url" value="<?php echo esc_attr(isset($form_release['installer_url']) ? $form_release['installer_url'] : ''); ?>"></div><div class="mukai-field"><label>SHA-256 del instalador</label><input required pattern="[A-Fa-f0-9]{64}" maxlength="64" class="code" name="sha256" value="<?php echo esc_attr(isset($form_release['sha256']) ? $form_release['sha256'] : ''); ?>"></div><div class="mukai-field"><label>Novedades que verá el usuario</label><textarea required rows="7" name="notes"><?php echo esc_textarea(isset($form_release['notes']) ? $form_release['notes'] : ''); ?></textarea></div><button type="submit" class="button button-primary button-large">Firmar y publicar actualización</button></form></section>
        <?php
    }

    private static function render_security_tab() {
        $public_key = get_option(self::PUBLIC_KEY_OPTION);
        $endpoint = rest_url(self::REST_NAMESPACE);
        ?>
        <section class="mukai-panel"><h2>Conexión segura</h2><p class="description">La clave privada nunca se muestra ni sale de WordPress. La aplicación contiene únicamente esta clave pública RSA.</p><div class="mukai-field"><label>Endpoint de la API</label><div class="mukai-copy-row"><input id="mukai-endpoint" readonly value="<?php echo esc_attr($endpoint); ?>"><button type="button" class="button" data-mukai-copy="mukai-endpoint">Copiar</button></div></div><div class="mukai-field"><label>Clave pública RSA-SHA256</label><textarea id="mukai-public-key" readonly rows="7" class="code"><?php echo esc_textarea($public_key); ?></textarea><p><button type="button" class="button" data-mukai-copy="mukai-public-key">Copiar</button></p></div><div class="mukai-update-state"><span class="dashicons dashicons-lock"></span><div><strong>Firma RSA-SHA256 activa</strong><br>Los códigos se almacenan como hash y los certificados quedan vinculados al equipo autorizado.</div></div></section>
        <?php
    }

    public static function handle_create_license() {
        self::require_admin_nonce('mukai_license_create');
        global $wpdb;
        $quantity = min(50, max(1, absint(isset($_POST['quantity']) ? $_POST['quantity'] : 1)));
        $duration_days = absint(isset($_POST['duration_days']) ? $_POST['duration_days'] : 90);
        if (!in_array($duration_days, array(30, 90, 180, 365), true)) {
            $duration_days = 90;
        }
        $max_devices = min(10, max(1, absint(isset($_POST['max_devices']) ? $_POST['max_devices'] : 1)));
        $now = current_time('mysql', true);
        $codes = array();

        for ($index = 0; $index < $quantity; $index++) {
            $code = self::generate_code();
            $inserted = $wpdb->insert(
                self::licenses_table(),
                array(
                    'license_key_hash' => wp_hash_password(self::normalise_code($code)),
                    'code_hint' => substr(self::normalise_code($code), 0, 5),
                    'status' => 'active',
                    'duration_days' => $duration_days,
                    'max_devices' => $max_devices,
                    'created_at' => $now,
                    'updated_at' => $now,
                ),
                array('%s', '%s', '%s', '%d', '%d', '%s', '%s')
            );
            if ($inserted) {
                $codes[] = $code;
            }
        }

        if (!$codes) {
            wp_die('No se pudieron crear las licencias. Revisa la base de datos e inténtalo de nuevo.');
        }
        set_transient(self::CODES_TRANSIENT . '_' . get_current_user_id(), $codes, MINUTE_IN_SECONDS * 15);
        self::redirect_admin(array('tab' => 'licenses', 'mukai_action_done' => count($codes)));
    }

    public static function handle_bulk_action() {
        self::require_admin_nonce('mukai_license_bulk_action');
        global $wpdb;

        $operation = isset($_POST['bulk_operation']) ? sanitize_key(wp_unslash($_POST['bulk_operation'])) : '';
        $license_ids = isset($_POST['license_ids']) ? (array) wp_unslash($_POST['license_ids']) : array();
        $quick_action = isset($_POST['quick_action']) ? sanitize_text_field(wp_unslash($_POST['quick_action'])) : '';

        if ($quick_action !== '' && preg_match('/^(revoke|reactivate|extend_90|reset_devices):(\d+)$/', $quick_action, $matches)) {
            $operation = $matches[1];
            $license_ids = array($matches[2]);
        }

        $allowed_operations = array('revoke', 'reactivate', 'extend_90', 'reset_devices');
        $license_ids = array_slice(array_values(array_unique(array_filter(array_map('absint', $license_ids)))), 0, 100);
        if (!in_array($operation, $allowed_operations, true) || !$license_ids) {
            self::redirect_admin(array('tab' => 'licenses'));
        }

        $updated = 0;
        $now = current_time('mysql', true);
        foreach ($license_ids as $license_id) {
            $license = $wpdb->get_row($wpdb->prepare(
                'SELECT id, status, duration_days, activated_at, expires_at FROM ' . self::licenses_table() . ' WHERE id = %d',
                $license_id
            ));
            if (!$license) {
                continue;
            }

            if ($operation === 'reset_devices') {
                $wpdb->delete(self::devices_table(), array('license_id' => $license_id), array('%d'));
                $updated++;
                continue;
            }

            if ($operation === 'revoke') {
                $result = $wpdb->update(
                    self::licenses_table(),
                    array('status' => 'revoked', 'updated_at' => $now),
                    array('id' => $license_id),
                    array('%s', '%s'),
                    array('%d')
                );
            } elseif ($operation === 'reactivate') {
                $data = array('status' => 'active', 'updated_at' => $now);
                $formats = array('%s', '%s');
                if ($license->activated_at && (!$license->expires_at || strtotime($license->expires_at . ' UTC') <= time())) {
                    $data['expires_at'] = gmdate('Y-m-d H:i:s', time() + max(1, absint($license->duration_days)) * DAY_IN_SECONDS);
                    $formats[] = '%s';
                }
                $result = $wpdb->update(self::licenses_table(), $data, array('id' => $license_id), $formats, array('%d'));
            } else {
                $data = array('status' => 'active', 'updated_at' => $now);
                $formats = array('%s', '%s');
                if ($license->activated_at) {
                    $base_timestamp = $license->expires_at ? strtotime($license->expires_at . ' UTC') : time();
                    $base_timestamp = max(time(), $base_timestamp ?: time());
                    $data['expires_at'] = gmdate('Y-m-d H:i:s', $base_timestamp + 90 * DAY_IN_SECONDS);
                    $formats[] = '%s';
                } else {
                    $data['duration_days'] = max(1, absint($license->duration_days)) + 90;
                    $formats[] = '%d';
                }
                $result = $wpdb->update(self::licenses_table(), $data, array('id' => $license_id), $formats, array('%d'));
            }

            if ($result !== false) {
                $updated++;
            }
        }

        self::redirect_admin(array('tab' => 'licenses', 'mukai_action_done' => $updated));
    }

    public static function handle_github_check() {
        self::require_admin_nonce('mukai_github_check');
        delete_transient(self::GITHUB_RELEASE_TRANSIENT);
        self::get_latest_github_release(true);
        self::redirect_admin(array('tab' => 'updates', 'mukai_github_checked' => '1'));
    }

    public static function handle_publish_update() {
        self::require_admin_nonce('mukai_release_publish');

        $version = trim(sanitize_text_field(isset($_POST['version']) ? wp_unslash($_POST['version']) : ''));
        $installer_url = esc_url_raw(trim(isset($_POST['installer_url']) ? wp_unslash($_POST['installer_url']) : ''));
        $sha256 = strtolower(preg_replace('/[^a-fA-F0-9]/', '', isset($_POST['sha256']) ? wp_unslash($_POST['sha256']) : ''));
        $notes = trim(sanitize_textarea_field(isset($_POST['notes']) ? wp_unslash($_POST['notes']) : ''));

        $release = array(
            'installer_url' => $installer_url,
            'notes' => $notes,
            'published_at' => gmdate('c'),
            'sha256' => $sha256,
            'version' => $version,
        );
        if (!self::is_valid_release($release)) {
            wp_die('Invalid update data. Use a semantic version, an HTTPS installer URL, a SHA-256 hash, and release notes.');
        }

        update_option(self::UPDATE_OPTION, $release, false);
        wp_safe_redirect(add_query_arg(
            array('page' => 'mukai-licenses', 'tab' => 'updates', 'mukai_release_published' => '1'),
            admin_url('admin.php')
        ));
        exit;
    }

    public static function handle_revoke_license() {
        $license_id = absint(isset($_POST['license_id']) ? $_POST['license_id'] : 0);
        self::require_admin_nonce('mukai_license_revoke_' . $license_id);
        global $wpdb;
        $wpdb->update(self::licenses_table(), array('status' => 'revoked', 'updated_at' => current_time('mysql', true)), array('id' => $license_id), array('%s', '%s'), array('%d'));
        self::redirect_admin();
    }

    public static function handle_reset_device() {
        $license_id = absint(isset($_POST['license_id']) ? $_POST['license_id'] : 0);
        self::require_admin_nonce('mukai_license_reset_' . $license_id);
        global $wpdb;
        $wpdb->delete(self::devices_table(), array('license_id' => $license_id), array('%d'));
        self::redirect_admin();
    }

    private static function require_admin_nonce($action) {
        if (!current_user_can('manage_options')) {
            wp_die('Unauthorized.');
        }
        check_admin_referer($action);
    }

    private static function redirect_admin($args = array()) {
        wp_safe_redirect(add_query_arg(array_merge(array('page' => 'mukai-licenses'), $args), admin_url('admin.php')));
        exit;
    }

    private static function generate_code() {
        $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
        $code = '';
        for ($index = 0; $index < 25; $index++) {
            $code .= $alphabet[random_int(0, strlen($alphabet) - 1)];
        }
        return implode('-', str_split($code, 5));
    }
}

register_activation_hook(__FILE__, array('Mukai_License_Server', 'activate'));
Mukai_License_Server::boot();
