-- Keep the Library bucket private and allow the audio containers accepted by the server.
-- This is configuration-only; it preserves every existing MIME entry and file object.
begin;
do $$
declare
  bucket storage.buckets%rowtype;
  required_mimes text[] := array[
    'application/octet-stream',
    'audio/aac', 'audio/flac', 'audio/mp3', 'audio/mp4', 'audio/mpeg',
    'audio/ogg', 'audio/wav', 'audio/webm', 'audio/x-flac', 'audio/x-m4a', 'audio/x-wav'
  ];
begin
  select * into bucket from storage.buckets where id='postriff-library' for update;
  if not found then
    insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
    values('postriff-library','postriff-library',false,52428800,required_mimes);
  else
    if bucket.name is distinct from 'postriff-library'
       or bucket.public is distinct from false
       or bucket.file_size_limit is distinct from 52428800 then
      raise exception 'Existing postriff-library bucket does not match the verified private 50 MiB policy.';
    end if;
    update storage.buckets
    set allowed_mime_types = array(
      select distinct mime
      from unnest(coalesce(bucket.allowed_mime_types,array[]::text[]) || required_mimes) as allowed(mime)
      order by mime
    )
    where id='postriff-library';
  end if;
end $$;
commit;
