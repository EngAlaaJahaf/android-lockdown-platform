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
-- Name: androidkioskpolicy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.androidkioskpolicy (
    config_data_item_id bigint NOT NULL,
    kiosk_mode integer DEFAULT 0 NOT NULL,
    launcher_type integer DEFAULT 2,
    enable_default_app boolean DEFAULT false NOT NULL,
    default_kiosk_app bigint,
    default_app_launch_timeout integer DEFAULT '-1'::integer NOT NULL,
    default_app_launch_mode integer DEFAULT 0 NOT NULL,
    wallpaper public.citext,
    show_me_mdm_app boolean DEFAULT true NOT NULL,
    allow_task_manager boolean DEFAULT true NOT NULL,
    allow_system_bar boolean DEFAULT true NOT NULL,
    allow_navigation_bar boolean DEFAULT true NOT NULL,
    allow_status_bar boolean DEFAULT true NOT NULL,
    allow_status_bar_expansion boolean DEFAULT true NOT NULL,
    allow_home_button boolean DEFAULT true NOT NULL,
    allow_volume_button boolean,
    ring_volume integer DEFAULT '-1'::integer,
    media_volume integer DEFAULT '-1'::integer,
    notification_volume integer DEFAULT '-1'::integer,
    alarm_volume integer DEFAULT '-1'::integer,
    is_stay_awake_on_charging boolean DEFAULT true,
    allow_power_button boolean DEFAULT true NOT NULL,
    allow_shutdown boolean DEFAULT true,
    allow_key_guard boolean DEFAULT true,
    allow_notification boolean DEFAULT true,
    allow_system_error_dialog boolean DEFAULT false,
    allow_recent_apps boolean DEFAULT true,
    allow_back_button boolean DEFAULT true NOT NULL,
    allow_custom_settings boolean DEFAULT false,
    auto_distribute_apps boolean DEFAULT true NOT NULL,
    auto_distribute_webapp boolean DEFAULT true NOT NULL,
    idle_refresh_timeout integer DEFAULT '-1'::integer,
    allow_sim_unlock boolean,
    exit_kiosk_password_id bigint,
    allow_multiwindow boolean,
    allow_notification_badge boolean DEFAULT false NOT NULL,
    clear_cookies_on_idle_timeout boolean DEFAULT true NOT NULL,
    clear_cache_on_idle_timeout boolean DEFAULT false NOT NULL,
    CONSTRAINT androidkioskpolicy_33677854_c CHECK ((length((wallpaper)::text) <= 250))
);


--
-- Name: androidkioskpolicy androidkioskpolicy_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.androidkioskpolicy
    ADD CONSTRAINT androidkioskpolicy_pk PRIMARY KEY (config_data_item_id);


--
-- Name: androidkioskpolicy_fk2_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX androidkioskpolicy_fk2_idx ON public.androidkioskpolicy USING btree (default_kiosk_app);


--
-- Name: androidkioskpolicy_fk3_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX androidkioskpolicy_fk3_idx ON public.androidkioskpolicy USING btree (exit_kiosk_password_id);


--
-- Name: androidkioskpolicy androidkioskpolicy_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.androidkioskpolicy
    ADD CONSTRAINT androidkioskpolicy_fk FOREIGN KEY (config_data_item_id) REFERENCES public.configdataitem(config_data_item_id) ON DELETE CASCADE;


--
-- Name: androidkioskpolicy androidkioskpolicy_fk2; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.androidkioskpolicy
    ADD CONSTRAINT androidkioskpolicy_fk2 FOREIGN KEY (default_kiosk_app) REFERENCES public.mdappgroupdetails(app_group_id) ON DELETE CASCADE;


--
-- Name: androidkioskpolicy androidkioskpolicy_fk3; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.androidkioskpolicy
    ADD CONSTRAINT androidkioskpolicy_fk3 FOREIGN KEY (exit_kiosk_password_id) REFERENCES public.mdmmanagedpassword(managed_password_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

