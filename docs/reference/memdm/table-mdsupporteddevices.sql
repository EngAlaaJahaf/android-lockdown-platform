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
-- Name: mdsupporteddevices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mdsupporteddevices (
    supported_device_id bigint NOT NULL,
    manufacturer public.citext,
    model_name public.citext,
    model_code public.citext NOT NULL,
    form_factor public.citext,
    screen_size public.citext,
    platform_type public.citext,
    CONSTRAINT mdsupporteddevices_1675450879_c CHECK ((length((model_name)::text) <= 250)),
    CONSTRAINT mdsupporteddevices_1675765405_c CHECK ((length((model_code)::text) <= 250)),
    CONSTRAINT mdsupporteddevices_2139406324_c CHECK ((length((screen_size)::text) <= 250)),
    CONSTRAINT mdsupporteddevices_227557078_c CHECK ((length((form_factor)::text) <= 250)),
    CONSTRAINT mdsupporteddevices_347933649_c CHECK ((length((manufacturer)::text) <= 250)),
    CONSTRAINT mdsupporteddevices_611108986_c CHECK ((length((platform_type)::text) <= 250))
);


--
-- Name: mdsupporteddevices mdsupporteddevices_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mdsupporteddevices
    ADD CONSTRAINT mdsupporteddevices_pk PRIMARY KEY (supported_device_id);


--
-- PostgreSQL database dump complete
--

