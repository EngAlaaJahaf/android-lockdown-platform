--
-- PostgreSQL database dump
--

-- Dumped from database version 14.13
-- Dumped by pg_dump version 14.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: mdrestriction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mdrestriction (
    resource_id bigint NOT NULL,
    scope integer DEFAULT 0 NOT NULL,
    allow_clipboard integer DEFAULT '-1'::integer NOT NULL,
    allow_google_crash_report integer DEFAULT '-1'::integer NOT NULL,
    allow_cellular_data integer DEFAULT '-1'::integer NOT NULL,
    allow_disabling_cellular_data integer DEFAULT '-1'::integer NOT NULL,
    allow_disabling_gps integer DEFAULT '-1'::integer NOT NULL,
    allow_bluetooth_tethering integer DEFAULT '-1'::integer NOT NULL,
    allow_mock_location integer DEFAULT '-1'::integer NOT NULL,
    allow_microphone integer DEFAULT '-1'::integer NOT NULL,
    allow_wifi integer DEFAULT '-1'::integer NOT NULL,
    allow_whitelist_wifi_only integer DEFAULT 0 NOT NULL,
    allow_sd_card_write integer DEFAULT '-1'::integer NOT NULL,
    allow_bluetooth integer DEFAULT '-1'::integer NOT NULL,
    allow_background_data integer DEFAULT '-1'::integer NOT NULL,
    allow_power_off integer DEFAULT '-1'::integer NOT NULL,
    allow_factory_reset integer DEFAULT '-1'::integer NOT NULL,
    allow_sd_card integer DEFAULT '-1'::integer NOT NULL,
    allow_nfc integer DEFAULT '-1'::integer NOT NULL,
    allow_settings integer DEFAULT '-1'::integer NOT NULL,
    allow_tethering integer DEFAULT '-1'::integer NOT NULL,
    allow_wallpaper_change integer DEFAULT '-1'::integer NOT NULL,
    allow_usb integer DEFAULT '-1'::integer NOT NULL,
    allow_usb_tethering integer DEFAULT '-1'::integer NOT NULL,
    allow_usb_debug integer DEFAULT '-1'::integer NOT NULL,
    allow_backup_restore integer DEFAULT '-1'::integer NOT NULL,
    allow_google_backup integer DEFAULT '-1'::integer NOT NULL,
    allow_wifi_tethering integer DEFAULT '-1'::integer NOT NULL,
    allow_usb_media_player integer DEFAULT '-1'::integer NOT NULL,
    allow_statusbar_expansion integer DEFAULT '-1'::integer NOT NULL,
    allow_ota_upgrade integer DEFAULT '-1'::integer NOT NULL,
    allow_vpn integer DEFAULT '-1'::integer NOT NULL,
    allow_screen_capture integer DEFAULT '-1'::integer NOT NULL,
    allow_camera integer DEFAULT '-1'::integer NOT NULL,
    allow_roaming_sync integer DEFAULT '-1'::integer NOT NULL,
    allow_roaming_voice_calls integer DEFAULT '-1'::integer NOT NULL,
    allow_roaming_push integer DEFAULT '-1'::integer NOT NULL,
    allow_roaming_data integer DEFAULT '-1'::integer NOT NULL,
    browser_allow_fraud_warning integer DEFAULT '-1'::integer NOT NULL,
    browser_allow_popups integer DEFAULT '-1'::integer NOT NULL,
    browser_allow_javascript integer DEFAULT '-1'::integer NOT NULL,
    browser_allow_autofill integer DEFAULT '-1'::integer NOT NULL,
    browser_allow_cookies integer DEFAULT '-1'::integer NOT NULL,
    allow_android_browser integer DEFAULT '-1'::integer NOT NULL,
    allow_android_market integer DEFAULT '-1'::integer NOT NULL,
    allow_non_market_apps integer DEFAULT '-1'::integer NOT NULL,
    allow_personal_space_non_market_apps integer DEFAULT '-1'::integer NOT NULL,
    allow_you_tube integer DEFAULT '-1'::integer NOT NULL,
    allow_voice_dialer integer DEFAULT '-1'::integer NOT NULL,
    allow_install_app integer DEFAULT '-1'::integer NOT NULL,
    allow_uninstall_app integer DEFAULT '-1'::integer NOT NULL,
    device_admin_enabled integer DEFAULT '-1'::integer NOT NULL,
    allow_user_add_accounts integer DEFAULT '-1'::integer NOT NULL,
    allow_s_finder integer DEFAULT '-1'::integer NOT NULL,
    allow_air_command integer DEFAULT '-1'::integer NOT NULL,
    allow_air_view integer DEFAULT '-1'::integer NOT NULL,
    allow_user_creation integer DEFAULT '-1'::integer NOT NULL,
    allow_s_voice integer DEFAULT '-1'::integer NOT NULL,
    allow_stop_system_app integer DEFAULT '-1'::integer NOT NULL,
    allow_activation_lock integer DEFAULT '-1'::integer NOT NULL,
    allow_airplane_mode integer DEFAULT '-1'::integer NOT NULL,
    allow_android_beam integer DEFAULT '-1'::integer NOT NULL,
    allow_background_process_limit integer DEFAULT '-1'::integer NOT NULL,
    allow_s_beam integer DEFAULT '-1'::integer NOT NULL,
    allow_wifi_direct integer DEFAULT '-1'::integer NOT NULL,
    allow_headphone integer DEFAULT '-1'::integer NOT NULL,
    allow_smart_clip_mode integer DEFAULT '-1'::integer NOT NULL,
    allow_clipboard_share integer DEFAULT '-1'::integer NOT NULL,
    allow_firmware_recovery integer DEFAULT '-1'::integer NOT NULL,
    allow_sdcard_move integer DEFAULT '-1'::integer NOT NULL,
    allow_safe_mode integer DEFAULT '-1'::integer NOT NULL,
    allow_home_key integer DEFAULT '-1'::integer NOT NULL,
    allow_lock_screen_menu integer DEFAULT '-1'::integer NOT NULL,
    allow_developer_mode integer DEFAULT '-1'::integer NOT NULL,
    allow_kill_activity_on_leave integer DEFAULT '-1'::integer NOT NULL,
    allow_lock_screen_view integer DEFAULT '-1'::integer NOT NULL,
    allow_sharelist integer DEFAULT '-1'::integer NOT NULL,
    allow_user_mobile_data_limit integer DEFAULT '-1'::integer NOT NULL,
    allow_date_time_change integer DEFAULT '-1'::integer NOT NULL,
    allow_google_account_auto_sync integer DEFAULT '-1'::integer NOT NULL,
    allow_user_profile integer DEFAULT '-1'::integer NOT NULL,
    allow_app_notification_mode integer DEFAULT '-1'::integer NOT NULL,
    allow_audio_record integer DEFAULT '-1'::integer NOT NULL,
    allow_video_record integer DEFAULT '-1'::integer NOT NULL,
    allow_usb_host_storage integer DEFAULT '-1'::integer NOT NULL,
    allow_use_network_time integer DEFAULT '-1'::integer NOT NULL,
    allow_gmail integer DEFAULT '-1'::integer NOT NULL,
    allow_google_maps integer DEFAULT '-1'::integer NOT NULL,
    allow_bt_discoverable integer DEFAULT '-1'::integer NOT NULL,
    allow_bt_pairing integer DEFAULT '-1'::integer NOT NULL,
    allow_bt_outgoing_calls integer DEFAULT '-1'::integer NOT NULL,
    allow_bt_pc_connection integer DEFAULT '-1'::integer NOT NULL,
    allow_bt_data_transfer integer DEFAULT '-1'::integer NOT NULL,
    allow_emergency_calls_only integer DEFAULT '-1'::integer NOT NULL,
    allow_incoming_mms integer DEFAULT '-1'::integer NOT NULL,
    allow_outgoing_mms integer DEFAULT '-1'::integer NOT NULL,
    allow_sms integer DEFAULT '-1'::integer NOT NULL,
    allow_call integer DEFAULT '-1'::integer NOT NULL,
    allow_mms integer DEFAULT '-1'::integer NOT NULL,
    allow_incoming_sms integer DEFAULT '-1'::integer NOT NULL,
    allow_outgoing_sms integer DEFAULT '-1'::integer NOT NULL,
    allow_incoming_call integer DEFAULT '-1'::integer NOT NULL,
    allow_outgoing_call integer DEFAULT '-1'::integer NOT NULL,
    allow_other_keypad integer DEFAULT '-1'::integer NOT NULL,
    allow_knox_app_store integer DEFAULT '-1'::integer NOT NULL,
    allow_contacts_outside integer DEFAULT '-1'::integer NOT NULL,
    app_permission_policy integer DEFAULT '-1'::integer NOT NULL,
    allow_play_protect_monitoring integer DEFAULT 2 NOT NULL,
    allow_keyguard_camera boolean DEFAULT true NOT NULL,
    allow_camera_in_keyguard integer DEFAULT '-1'::integer NOT NULL,
    allow_keyguard_notifications integer DEFAULT 0 NOT NULL,
    allow_trust_agents boolean DEFAULT true NOT NULL,
    allow_keyguard_trust_agents integer DEFAULT '-1'::integer NOT NULL,
    allow_all_apps_access integer DEFAULT 0 NOT NULL,
    db_updated_time bigint DEFAULT '0'::bigint NOT NULL
);


--
-- Name: mdrestriction mdrestriction_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdrestriction
    ADD CONSTRAINT mdrestriction_pk PRIMARY KEY (resource_id, scope);


--
-- Name: mdrestriction_fk1_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX mdrestriction_fk1_idx ON public.mdrestriction USING btree (resource_id);


--
-- Name: mdrestriction mdrestriction_fk1; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdrestriction
    ADD CONSTRAINT mdrestriction_fk1 FOREIGN KEY (resource_id) REFERENCES public.manageddevice(resource_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

