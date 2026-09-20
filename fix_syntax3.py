import os

file_path = r'e:\ThinAptm0707\seedvis_app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

bad_block = '''            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=120)
                return True, ""
            finally:
                self._ffmpeg_sem.release()

            except subprocess.TimeoutExpired:'''

good_block = '''            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=120)
                return True, ""
            except subprocess.TimeoutExpired:'''

content = content.replace(bad_block, good_block)

# Now we need to add the finally block at the end of the excepts.
old_excepts = '''            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                return False, err_msg
        except Exception as ex:
            return False, str(ex)'''

new_excepts = '''            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                return False, err_msg
            finally:
                self._ffmpeg_sem.release()
        except Exception as ex:
            if hasattr(self, '_ffmpeg_sem'):
                try: self._ffmpeg_sem.release()
                except: pass
            return False, str(ex)'''

content = content.replace(old_excepts, new_excepts)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

